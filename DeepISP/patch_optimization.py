import torch
import torch.nn as nn
import torch.optim as optim
from torchvision import transforms
from torchvision.models import resnet50
from skimage.metrics import structural_similarity as ssim
import numpy as np
from PIL import Image
from load_data import extract_bayer_channels
import tensorflow as tf
from keras.models import Model
from keras import backend as K
from keras.applications.vgg16 import VGG16
import argparse
import os
from network import network
import imageio.v2 as imageio
from load_data import load_testing_data, load_testing_inp
import time


PATCH_HEIGHT = 224
PATCH_WIDTH = 224

parser = argparse.ArgumentParser()

parser.add_argument('-w' ,'--weights_file', type = str, default = 'weights2_0191.h5' , help = 'best weight file name (only prefix while evaluating)')
parser.add_argument('-dataset' ,'--dataset_path', type = str, default = './DeepISP/input_raw_images/' , help = 'complete path for the dataset')
parser.add_argument('-path' ,'--main_path', type = str, default = './DeepISP/' , help = 'main path where the result/experiment folders are stored')
parser.add_argument('-res' ,'--results_folder', type = str, default = 'results' , help = 'folder to save inference results')



args = parser.parse_args()
weights_file = args.weights_file
dataset_dir = args.dataset_path
current_path = args.main_path
res_folder = args.results_folder

# os.mkdir(os.path.join(current_path,res_folder))

def clip_eps(tensor, eps):
	# clip the values of the tensor to a given range and return it
	return tf.clip_by_value(tensor, clip_value_min=-eps,
		clip_value_max=eps)

# Load and preprocess the image
def load_image(image_path):
    # I = np.asarray(imageio.imread(image_path))
    # I = extract_bayer_channels(I)
    # return np.expand_dims(I, axis=0)

    I = np.asarray(imageio.imread(image_path))

    # Apply Bayer channel extraction
    I = extract_bayer_channels(I)

    if I.shape[0] != PATCH_HEIGHT or I.shape[1] != PATCH_WIDTH:
        raise ValueError("Extracted patch does not match specified dimensions: ({}, {}).".format(PATCH_WIDTH, PATCH_HEIGHT))

    # Create an array to hold the image in the expected format
    raw_img = np.zeros((1, PATCH_HEIGHT, PATCH_WIDTH, 4))  # Assuming the extracted image has 4 channels
    raw_img[0, :] = I

    return raw_img

def save_image(patched_image, file_path):
    patched_image = np.uint8(patched_image * 255.0)  # Convert from [0, 1] to [0, 255]
    imageio.imwrite(file_path, patched_image)

# Define the model (assuming a pretrained ResNet-50 for example)
def get_model():
    in_shape = (224,224,4)
    base_vgg = VGG16(weights = 'imagenet', include_top = False, input_shape = (448,448,3))
    vgg = Model(inputs = base_vgg.input, outputs = base_vgg.get_layer('block4_pool').output)
    for layer in vgg.layers:
        layer.trainable = False
    d_model = network(vgg, inp_shape = in_shape, trainable = False)
    filename = os.path.join(current_path, weights_file)
    d_model.load_weights(filename)
    return d_model

# SSIM loss function
def ssim_loss(original, modified):
    original = original.detach().cpu().numpy()
    modified = modified.detach().cpu().numpy()
    score = ssim(original, modified, data_range=modified.max() - modified.min(), multichannel=True)
    return torch.tensor(1 - score)  # 1 - SSIM to minimize the loss

# FGSM attack to optimize the patch
def fgsm_patch(image, model, epsilon, max_iterations, loss_threshold):
    image_height, image_width = image.shape[1], image.shape[2]
    print("Image shape: ", image.shape)
    patch_size = (int(image_height * 0.1), int(image_width * 0.1)) # To adjust Patch Size
    original_image,_,_,_,_ = model.predict(image)
    print(original_image.shape)
    # Patch Location - Centre of Image
    top_left_x = (image_width - patch_size[0]) // 2
    top_left_y = (image_height - patch_size[1]) // 2

    patch = tf.Variable(tf.random.uniform([1, patch_size[1], patch_size[0], 4], dtype=tf.float32, minval=0, maxval=1))
    print("Patch initial shape:", patch.shape)  # Debug statement
    print("Patch elements:", tf.size(patch).numpy())
    best_patch = tf.identity(patch)
    best_ssim = float('inf')
    best_patched_image = tf.identity(original_image)
    image = tf.cast(image, tf.float32) / 255.0

    for i in range(max_iterations):
        with tf.GradientTape() as tape:
            tape.watch(patch)
            patched_image = tf.identity(image)
            # print("Reshaping patch to:", patch_size[1], patch_size[0], 4) 
            patch_values = tf.reshape(patch, [patch_size[1], patch_size[0], 4])  # Ensure correct reshape
            indices = [[0, y, x, c] for y in range(top_left_y, top_left_y + patch_size[1])
                                    for x in range(top_left_x, top_left_x + patch_size[0])
                                    for c in range(4)]
            patched_image = tf.tensor_scatter_nd_update(patched_image, indices, tf.reshape(patch_values, [-1]))
            # output_with_patch,_, _, _, _ = model.predict(patched_image)
            output_with_patch,_, _, _, _ = model(patched_image, training=False)
            loss = 1 - tf.reduce_mean(tf.image.ssim(original_image[0], output_with_patch[0], max_val=1.0))
            print(loss)
        gradients = tape.gradient(loss, patch)
        patch.assign_add(epsilon * tf.sign(gradients))
        patch.assign(tf.clip_by_value(patch, 0, 1))  # Ensure the values remain in [0, 1]

        if loss.numpy() < best_ssim:
            best_ssim = loss.numpy()
            best_patch = tf.identity(patch)
            best_patched_image = tf.identity(output_with_patch)
        
        if best_ssim < loss_threshold:
            break

    return original_image, best_patched_image


def process_raw_images(model):
    raw_imgs = load_testing_inp(dataset_dir, 224, 224)
    t1=time.time()
    out,_,_,_,_ = model.predict(raw_imgs)
    print(out.shape)
    t2=time.time()
    t = (t2-t1)/raw_imgs.shape[0]
    print(t)
    for i in range(out.shape[0]):
        I = np.uint8(out[i,:,:,:]*255.0)
        imageio.imwrite(os.path.join(current_path, res_folder) + '/' +  str(i) + '.png', I)
    
# Main function to run the attack
def main():
    image_path = current_path + 'input_raw_images/0.png'
    image = load_image(image_path)
    # image = load_testing_inp(dataset_dir, 224, 224)[0,:,:,:]
    epsilon = 0.01  # Perturbation level
    max_iterations = 3
    loss_threshold = 1
    d_model = get_model()
    original_image, best_patched_image = fgsm_patch(image, d_model, epsilon, max_iterations, loss_threshold)
    print(f"Shapes: {original_image.shape} {best_patched_image.shape}")
    output_path = os.path.join(current_path, res_folder) + '/'
    save_image(np.uint8(best_patched_image[0]*255.0), output_path + "best_patch_image.png")
    save_image(np.uint8(original_image[0]*255.0), output_path + "original_image.png")
    print("Optimized patch generated and saved.")
    process_raw_images(d_model)

if __name__ == "__main__":
    main()
