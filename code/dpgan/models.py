from .sync_batchnorm import DataParallelWithCallback
from . import generator as generators
from . import discriminator as discriminators
import os
import copy
import torch
import torch.nn as nn
from torch.nn import init
from . import losses as losses


class DP_GAN_model(nn.Module):
    def __init__(self, opt):
        super(DP_GAN_model, self).__init__()
        self.opt = opt
        #--- generator and discriminator ---
        self.netG = generators.DP_GAN_Generator(opt)
        if opt.phase == "train" or opt.phase == "eval":
            self.netD = discriminators.DP_GAN_Discriminator(opt)
        self.print_parameter_count()
        self.init_networks()
        #--- EMA of generator weights ---
        with torch.no_grad():
            self.netEMA = copy.deepcopy(self.netG) if not opt.no_EMA else None
        #--- load previous checkpoints if needed ---
        self.load_checkpoints()
        #--- perceptual loss ---#
        if opt.phase == "train":
            if opt.add_vgg_loss:
                self.VGG_loss = losses.VGGLoss(self.opt.gpu_ids)
        self.GAN_loss = losses.GANLoss()
        self.MSELoss = nn.MSELoss(reduction='mean')

    def align_loss(self, feats, feats_ref):
        loss_align = 0
        for f, fr in zip(feats, feats_ref):
            loss_align += self.MSELoss(f, fr)
        return loss_align

    def forward(self, image, label, mode, losses_computer):
        # Branching is applied to be compatible with DataParallel
        if mode == "losses_G":
            loss_G = 0
            fake = self.netG(label)
            output_D, scores, feats = self.netD(fake)
            _, _, feats_ref = self.netD(image)
            loss_G_adv = losses_computer.loss(output_D, label, for_real=True)
            loss_G += loss_G_adv
            loss_ms = self.GAN_loss(scores, True, for_discriminator=False)
            loss_G += loss_ms.item()
            loss_align = self.align_loss(feats, feats_ref)
            loss_G += loss_align
            if self.opt.add_vgg_loss:
                loss_G_vgg = self.opt.lambda_vgg * self.VGG_loss(fake, image)
                loss_G += loss_G_vgg
            else:
                loss_G_vgg = None
            return loss_G, [loss_G_adv, loss_G_vgg]

        if mode == "losses_D":
            loss_D = 0
            with torch.no_grad():
                fake = self.netG(label)
            output_D_fake, scores_fake, _ = self.netD(fake)
            loss_D_fake = losses_computer.loss(output_D_fake, label, for_real=False)
            loss_ms_fake = self.GAN_loss(scores_fake, False, for_discriminator=True)
            loss_D += loss_D_fake + loss_ms_fake.item()
            output_D_real, scores_real, _ = self.netD(image)
            loss_D_real = losses_computer.loss(output_D_real, label, for_real=True)
            loss_ms_real = self.GAN_loss(scores_real, True, for_discriminator=True)
            loss_D += loss_D_real + loss_ms_real.item()
            loss_D_lm = None
            return loss_D, [loss_D_fake, loss_D_real, loss_D_lm]

        if mode == "generate":
            with torch.no_grad():
                if self.opt.no_EMA:
                    fake = self.netG(label)
                else:
                    fake = self.netEMA(label)
            return fake

        if mode == "eval":
            with torch.no_grad():
                pred, _, _ = self.netD(image)
            return pred

    def load_checkpoints(self):
        if self.opt.phase == "test":
            which_iter = self.opt.ckpt_iter
            path = os.path.join(self.opt.checkpoints_dir, self.opt.name, "models", str(which_iter) + "_")
            if self.opt.no_EMA:
                self.netG.load_state_dict(torch.load(path + "G.pth"))
            else:
                self.netEMA.load_state_dict(torch.load(path + "EMA.pth"))
        elif self.opt.phase == "eval":
            which_iter = self.opt.ckpt_iter
            path = os.path.join(self.opt.checkpoints_dir, self.opt.name, "models", str(which_iter) + "_")
            self.netD.load_state_dict(torch.load(path + "D.pth"))
        elif self.opt.continue_train:
            which_iter = self.opt.which_iter
            path = os.path.join(self.opt.checkpoints_dir, self.opt.name, "models", str(which_iter) + "_")
            self.netG.load_state_dict(torch.load(path + "G.pth"))
            self.netD.load_state_dict(torch.load(path + "D.pth"))
            if not self.opt.no_EMA:
                self.netEMA.load_state_dict(torch.load(path + "EMA.pth"))

    def print_parameter_count(self):
        if self.opt.phase == "train":
            networks = [self.netG, self.netD]
        else:
            networks = [self.netG]
        for network in networks:
            param_count = 0
            for name, module in network.named_modules():
                if (isinstance(module, nn.Conv2d)
                        or isinstance(module, nn.Linear)
                        or isinstance(module, nn.Embedding)):
                    param_count += sum([p.data.nelement() for p in module.parameters()])
            print('Created', network.__class__.__name__, "with %d parameters" % param_count)

    def init_networks(self):
        def init_weights(m, gain=0.02):
            classname = m.__class__.__name__
            if classname.find('BatchNorm2d') != -1:
                if hasattr(m, 'weight') and m.weight is not None:
                    init.normal_(m.weight.data, 1.0, gain)
                if hasattr(m, 'bias') and m.bias is not None:
                    init.constant_(m.bias.data, 0.0)
            elif hasattr(m, 'weight') and (classname.find('Conv') != -1 or classname.find('Linear') != -1):
                init.xavier_normal_(m.weight.data, gain=gain)
                if hasattr(m, 'bias') and m.bias is not None:
                    init.constant_(m.bias.data, 0.0)

        if self.opt.phase == "train":
            networks = [self.netG, self.netD]
        else:
            networks = [self.netG]
        for net in networks:
            net.apply(init_weights)


def put_on_multi_gpus(model, opt):
    if opt.gpu_ids != "-1":
        gpus = list(map(int, opt.gpu_ids.split(",")))
        model = DataParallelWithCallback(model, device_ids=gpus).cuda()
    else:
        model.module = model
    assert len(opt.gpu_ids.split(",")) == 0 or opt.batch_size % len(opt.gpu_ids.split(",")) == 0
    return model


def preprocess_input(opt, data):
    data['input'] = data['input'].long()
    if opt.gpu_ids != "-1":
        data['input'] = data['input'].cuda()
        data['ground_truth'] = data['ground_truth'].cuda()
    label_map = data['input']
    bs, _, h, w = label_map.size()
    nc = opt.semantic_nc
    if opt.gpu_ids != "-1":
        input_label = torch.cuda.FloatTensor(bs, nc, h, w).zero_()
    else:
        input_label = torch.FloatTensor(bs, nc, h, w).zero_()
    #input_semantics = input_label.scatter_(1, label_map, 1.0)
    return data['ground_truth'], label_map


