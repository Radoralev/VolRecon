from torchvision import transforms
import matplotlib.pyplot as plt
from code.dataset.cgan_train_sparse import CGanTrainDataset, CGANTestDataset
import numpy as np
from code.cgan.cgan import Pix2PixModel

data_transform = transforms.Compose([
        transforms.Resize((600, 800)),
        transforms.ToTensor(),
    ])

class Pix2PixOptions:
    def __init__(self):
        self.isTrain=True
        self.resize_or_crop = 'resize'
        self.loadSize = 800
        self.fineSize = 512
        self.no_flip = False

root_dir2 = '../Rectified_colmap/'
root_dir1 = 'outputs_g_final/rgb/'
# Create the dataset
dataset = CGanTrainDataset(root_dir1, root_dir2, Pix2PixOptions(), True)



# Function to convert a tensor to a numpy array suitable for plotting
def tensor_to_img(img_tensor):
    # Convert tensor to numpy array
    img_np = img_tensor.numpy()
    
    # Reshape (C, H, W) -> (H, W, C)
    img_np = np.transpose(img_np, (1, 2, 0))
    
    # Scale pixel values back to 0-255
    img_np = img_np * 255
    
    # Convert to integers
    img_np = img_np.astype(np.uint8)
    
    return img_np

# Select the pairs to visualize
pairs_to_visualize = [0, 1, 2, 3, 4, 8, 9, 10]

# Start a new plot
fig, axs = plt.subplots(len(pairs_to_visualize), 2, figsize=(10, 5 * len(pairs_to_visualize)))

print(len(dataset))
# For each pair
for i, pair_idx in enumerate(pairs_to_visualize):
    # Get the pair
    pair = dataset[pair_idx]
    
    # For each image in the pair
    for j in range(2):
        # Compute subplot index
        ax = axs[i, j]

        if j == 0:  # input image
            img = pair['input']  # assuming one input image per pair
            ax.set_title('Input Image')
        else:  # ground truth
            img = pair['ground_truth'] # assuming one ground truth image per pair
            ax.set_title('Ground Truth Image')

        
        # Show the image
        ax.imshow(img)

        # Remove the axis
        ax.axis('off')

# Save the figure
plt.savefig('cgan_train_data.png', bbox_inches='tight')
plt.close()
