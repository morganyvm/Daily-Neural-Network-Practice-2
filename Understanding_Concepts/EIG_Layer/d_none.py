import tensorflow as tf
import numpy as np
import sys, os,cv2
from sklearn.utils import shuffle
from scipy.misc import imread,imresize
import matplotlib.pyplot as plt
from sklearn.preprocessing import OneHotEncoder
from skimage.transform import resize
from imgaug import augmenters as iaa
import imgaug as ia
from scipy.ndimage import zoom
import seaborn as sns
from scipy import linalg as LA

np.random.seed(0)
np.set_printoptions(precision = 3,suppress =True)
old_v = tf.logging.get_verbosity()
tf.logging.set_verbosity(tf.logging.ERROR)
from tensorflow.examples.tutorials.mnist import input_data

# def: relu activations
def np_relu(x): return x * (x > 0) + 0.01 *x* (x <= 0)
def d_np_relu(x): return 1. * (x > 0) + 0.01 * (x <= 0)
def np_tanh(x): return  np.tanh(x)
def d_np_tanh(x): return 1. - np_sigmoid(x) ** 2
def np_sigmoid(x): return  1/(1+np.exp(-x))
def d_np_sigmoid(x): return np_sigmoid(x) * (1.-np_sigmoid(x))

# def: fully connected layer
r = np.random.RandomState(1234)
class np_FNN():

    def __init__(self,inc,outc,act=np_relu,d_act = d_np_relu):
        self.w = r.normal(0,0.008,size=(inc, outc)).astype(np.float64)
        self.b = r.normal(0,0.0001,size=(outc)).astype(np.float64)
        self.m,self.v = np.zeros_like(self.w),np.zeros_like(self.w)
        self.mb,self.vb = np.zeros_like(self.b),np.zeros_like(self.b)
        self.act = act; self.d_act = d_act

    def getw(self): return self.w

    def feedforward(self,input):
        self.input  = input
        self.layer  = self.input.dot(self.w) + self.b
        self.layerA = self.act(self.layer)
        return self.layerA

    def backprop(self,grad,lr_rate):
        grad_1 = grad
        grad_2 = self.d_act(self.layer)
        grad_3 = self.input

        grad_middle = grad_1 * grad_2
        grad_b = grad_middle.sum(0) / grad.shape[0]
        grad = grad_3.T.dot(grad_middle) / grad.shape[0]
        grad_pass = grad_middle.dot(self.w.T)

        self.m = self.m * beta1 + (1. - beta1) * grad
        self.v = self.v * beta2 + (1. - beta2) * grad ** 2
        m_hat,v_hat = self.m/(1.-beta1), self.v/(1.-beta2)
        adam_middle =  m_hat * lr_rate / (np.sqrt(v_hat) + adam_e)
        self.w = self.w - adam_middle

        self.mb = self.mb * beta1 + (1. - beta1) * grad_b
        self.vb = self.vb * beta2 + (1. - beta2) * grad_b ** 2
        m_hat,v_hat = self.mb/(1.-beta1), self.vb/(1.-beta2)
        adam_middle =  m_hat * lr_rate / (np.sqrt(v_hat) + adam_e)
        self.b = self.b - adam_middle

        return grad_pass

# def: centering layer
class centering_layer():

    def __init__(self): pass

    def feedforward(self,input):
        x_mean = np.sum(input,axis=0) / input.shape[0]
        return input - x_mean

    def backprop(self,grad):
        return grad * ( 1. - 1./grad.shape[0])

# def: standardization_layer
class standardization_layer():

    def __init__(self): pass

    def feedforward(self,input,EPS=10e-5):
        self.input = input
        self.mean  = np.sum(input,axis=0) / input.shape[0]
        self.std   = np.sum( (self.input - self.mean) ** 2,0)  / input.shape[0]
        self.x_hat = (input - self.mean) / np.sqrt(self.std + EPS)
        return self.x_hat

    def backprop(self,grad,EPS=10e-5):
        dem = 1./(grad.shape[0] * np.sqrt(self.std + EPS ) )
        d_x = grad.shape[0] * grad - np.sum(grad,axis = 0) - self.x_hat*np.sum(grad*self.x_hat, axis=0)
        return d_x * dem

# def: zca whitening layer
class zca_whiten_layer():

    def __init__(self): pass

    def feedforward(self,input,EPS=0.06):
        self.input = input
        self.sigma = input.T.dot(input) / input.shape[0]
        self.eigenval,self.eigvector = LA.eigh(self.sigma)
        self.U = self.eigvector.dot(np.diag(1. / np.sqrt(self.eigenval+EPS))).dot(self.eigvector.T)
        self.whiten = input.dot(self.U)
        return self.whiten

    def backprop(self,grad,EPS=0.06):
        d_U = self.input.T.dot(grad)
        d_eig_value = self.eigvector.T.dot(d_U).dot(self.eigvector) * (-0.5) * np.diag(1. / (self.eigenval+EPS) ** 1.5)
        d_eig_vector = d_U.dot( (np.diag(1. / np.sqrt(self.eigenval+EPS)).dot(self.eigvector.T)).T  ) + \
                       (self.eigvector.dot(np.diag(1. / np.sqrt(self.eigenval+EPS)))).dot(d_U)
        E = np.ones((grad.shape[1],1)).dot(np.expand_dims(self.eigenval.T,0)) - np.expand_dims(self.eigenval,1).dot(np.ones((1,grad.shape[1])))
        K_matrix = 1./(E + np.eye(grad.shape[1])) - np.eye(grad.shape[1])
        np.fill_diagonal(d_eig_value,0.0)
        d_sigma = self.eigvector.dot(
                    K_matrix.T * (self.eigvector.T.dot(d_eig_vector)) + d_eig_value
                    ).dot(self.eigvector.T)
        d_x = grad.dot(self.U.T) + (2./grad.shape[0]) * self.input.dot(d_sigma)
        return d_x

# mnist = input_data.read_data_sets('../../Dataset/MNIST/', one_hot=True)
mnist = input_data.read_data_sets('../../Dataset/fashionmnist/',one_hot=True)
train_data, train_label, test_data, test_label = mnist.train.images, mnist.train.labels, mnist.test.images, mnist.test.labels

# Show some details and vis some of them
print(train_data.shape)
print(train_data.min(),train_data.max())
print(train_label.shape)
print(train_label.min(),train_label.max())
print(test_data.shape)
print(test_data.min(),test_data.max())
print(test_label.shape)
print(test_label.min(),test_label.max())
print('-----------------------')

# hyper
num_epoch = 15 ; batch_size = 250
learning_rate = 0.001
print_size  = 1
beta1,beta2,adam_e = 0.9,0.999,1e-40

# class of layers
l0 = np_FNN(28*28,26*26 ,act=np_tanh,d_act=d_np_tanh) # 26
l1 = np_FNN(26*26,16*16 ,act=np_relu,d_act=d_np_relu) # 16
l3 = np_FNN(16*16,10    ,act=np_relu,d_act=d_np_relu)

# train
train_cota,train_acca = 0,0 ; train_cot,train_acc = [],[]
test_cota,test_acca = 0,0; test_cot,test_acc = [],[]
for iter in range(num_epoch):

    # learning rate decay
    learning_rate = learning_rate * 0.99

    for current_data_index in range(0,len(train_data),batch_size):
        current_data = train_data[current_data_index:current_data_index+batch_size].astype(np.float64)
        current_label= train_label[current_data_index:current_data_index+batch_size].astype(np.float64)

        layer0 = l0.feedforward(current_data)
        layer1 = l1.feedforward(layer0)
        layer3 = l3.feedforward(layer1)

        cost = np.mean( layer3 - current_label )
        accuracy = np.mean(np.argmax(layer3,1) == np.argmax(current_label, 1))
        print('Current Iter: ', iter,' batch index: ', current_data_index, ' accuracy: ',accuracy, ' cost: ',cost,end='\r')
        train_cota = train_cota + cost; train_acca = train_acca + accuracy

        grad3 = l3.backprop(layer3 - current_label ,lr_rate=learning_rate)
        grad1 = l1.backprop(grad3,lr_rate=learning_rate)
        grad0 = l0.backprop(grad1,lr_rate = learning_rate)

    for current_data_index in range(0,len(test_data),batch_size):
        current_data = test_data[current_data_index:current_data_index+batch_size].astype(np.float64)
        current_label= test_label[current_data_index:current_data_index+batch_size].astype(np.float64)

        layer0 = l0.feedforward(current_data)
        layer1 = l1.feedforward(layer0)
        layer3 = l3.feedforward(layer1)

        cost = np.mean( layer3 - current_label )
        accuracy = np.mean(np.argmax(layer3,1) == np.argmax(current_label, 1))
        print('Current Iter: ', iter,' batch index: ', current_data_index, ' accuracy: ',accuracy, ' cost: ',cost,end='\r')
        test_cota = test_cota + cost; test_acca = test_acca + accuracy

    if iter % print_size==0:
        print("\n----------")
        print('Train Current Acc: ', train_acca/(len(train_data)/batch_size),' Current cost: ', train_cota/(len(train_data)/batch_size),end='\n')
        print('Test  Current Acc: ', test_acca/(len(test_data)/batch_size),' Current cost: ', test_cota/(len(test_data)/batch_size),end='\n')
        print("----------")

    train_acc.append(train_acca/(len(train_data)/batch_size));train_cot.append(train_cota/(len(train_data)/batch_size))
    train_cota,train_acca = 0,0
    test_acc.append(test_acca/(len(test_data)/batch_size));test_cot.append(test_cota/(len(test_data)/batch_size))
    test_cota,test_acca = 0,0

# after training is finished viz
train_acc = (train_acc-min(train_acc))/(max(train_acc)-min(train_acc))
train_cot = (train_cot-min(train_cot))/(max(train_cot)-min(train_cot))
test_acc = (test_acc-min(test_acc))/(max(test_acc)-min(test_acc))
test_cot = (test_cot-min(test_cot))/(max(test_cot)-min(test_cot))

plt.close('all')
plt.figure()
plt.plot(range(len(train_acc)),train_acc,color='red',label='acc ovt')
plt.plot(range(len(train_cot)),train_cot,color='green',label='cost ovt')
plt.legend()
plt.title("Train Average Accuracy / Cost Over Time")
plt.savefig('case d train.png')
plt.show()

plt.figure()
plt.plot(range(len(test_acc)),test_acc,color='red',label='acc ovt')
plt.plot(range(len(test_cot)),test_cot,color='green',label='cost ovt')
plt.legend()
plt.title("Test Average Accuracy / Cost Over Time")
plt.savefig('case d test.png')
plt.show()

# get 100 images from training to viz
def show_to_image(A,shape_value,vec=False):
    A = (A-A.min(1)[:,np.newaxis])/(A.max(1) - A.min(1))[:,np.newaxis]
    fig=plt.figure(figsize=(8, 8))
    columns = 10 ; rows = 10
    for i in range(1, columns*rows +1):
        fig.add_subplot(rows, columns, i)
        if vec:
            plt.imshow(A[i-1].reshape(2,5),cmap='gray')
            plt.axis('off')
        else:
            plt.imshow(A[i-1].reshape(shape_value,shape_value),cmap='gray')
            plt.axis('off')
    plt.show()

image_to_show = train_data[:100]
layer0 = l0.feedforward(image_to_show)
layer1 = l1.feedforward(layer0_special)
layer3 = l3.feedforward(layer1)

show_to_image(image_to_show,shape_value=28)
show_to_image(layer0,shape_value=26)
show_to_image(layer1,shape_value=16)
show_to_image(layer3,vec=True,shape_value=None)



# -- end code --
