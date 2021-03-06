import tensorflow as tf
import numpy as np
import sys, os,cv2
from sklearn.utils import shuffle
from scipy.misc import imread
from scipy.misc import imresize
import matplotlib.pyplot as plt
from sklearn.preprocessing import OneHotEncoder
from skimage.transform import resize
from imgaug import augmenters as iaa
import imgaug as ia

from scipy import linalg
from sklearn.base import TransformerMixin, BaseEstimator
from sklearn.utils.validation import check_is_fitted
from sklearn.utils import check_array, as_float_array

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3' 
np.random.seed(678)
tf.set_random_seed(678)
ia.seed(678)

def tf_elu(x): return tf.nn.elu(x)
def d_tf_elu(x): return tf.cast(tf.greater_equal(x,0),tf.float32)  + (tf_elu(tf.cast(tf.less(x,0),tf.float32) * x) + 1.0)
def tf_softmax(x): return tf.nn.softmax(x)
def unpickle(file):
    import pickle
    with open(file, 'rb') as fo:
        dict = pickle.load(fo, encoding='bytes')
    return dict

# data aug
seq = iaa.Sequential([  
iaa.CropAndPad(
    percent=(0, 0.2),
    pad_mode=["constant", "edge"],
    pad_cval=(0, 128)
),
iaa.Fliplr(1.0), # Horizontal flips
], random_order=True) # apply augmenters in random order

# Code from: https://stackoverflow.com/questions/31528800/how-to-implement-zca-whitening-python
class ZCA(BaseEstimator, TransformerMixin):
    def __init__(self, regularization=1e-6, copy=False):
        self.regularization = regularization
        self.copy = copy

    def fit(self, X, y=None):
        """Compute the mean, whitening and dewhitening matrices.
        Parameters
        ----------
        X : array-like with shape [n_samples, n_features]
            The data used to compute the mean, whitening and dewhitening
            matrices.
        """
        X = check_array(X, accept_sparse=False, copy=self.copy,ensure_2d=True)
        self.mean_ = X.mean(axis=0)
        X_ = X - self.mean_
        cov = np.dot(X_.T, X_) / (X_.shape[0]-1)
        U, S, _ = linalg.svd(cov)
        s = np.sqrt(S.clip(self.regularization))
        s_inv = np.diag(1./s)
        s = np.diag(s)
        self.whiten_ = np.dot(np.dot(U, s_inv), U.T)
        self.dewhiten_ = np.dot(np.dot(U, s), U.T)
        return self

    def transform(self, X, y=None, copy=None):
        """Perform ZCA whitening
        Parameters
        ----------
        X : array-like with shape [n_samples, n_features]
            The data to whiten along the features axis.
        """
        check_is_fitted(self, 'mean_')
        X = as_float_array(X, copy=self.copy)
        return np.dot(X - self.mean_, self.whiten_.T)

# code from: https://github.com/tensorflow/tensorflow/issues/8246
def tf_repeat(tensor, repeats):
    """
    Args:

    input: A Tensor. 1-D or higher.
    repeats: A list. Number of repeat for each dimension, length must be the same as the number of dimensions in input

    Returns:
    
    A Tensor. Has the same type as input. Has the shape of tensor.shape * repeats
    """
    expanded_tensor = tf.expand_dims(tensor, -1)
    multiples = [1] + repeats
    tiled_tensor = tf.tile(expanded_tensor, multiples = multiples)
    repeated_tesnor = tf.reshape(tiled_tensor, tf.shape(tensor) * repeats)
    return repeated_tesnor

# Convolution Layer
class CNN():
    
    def __init__(self,k,inc,out,act,d_act):
        self.w = tf.Variable(tf.random_normal([k,k,inc,out],stddev=0.05))
        self.m,self.v_prev = tf.Variable(tf.zeros_like(self.w)),tf.Variable(tf.zeros_like(self.w))
        self.v_hat_prev = tf.Variable(tf.zeros_like(self.w))
        self.act,self.d_act = act,d_act
    def getw(self): return self.w

    def feedforward(self,input,stride=1,padding='SAME',droprate=1.0,res=False):
        self.input  = input
        self.layer  = tf.nn.dropout(tf.nn.conv2d(input,self.w,strides=[1,stride,stride,1],padding=padding) ,droprate)
        self.layerA = self.act(self.layer)
        return self.layerA 

    def backprop(self,gradient,learning_rate_change,batch_size_dynamic,stride=1,padding='SAME',mom=False,adam=False,awsgrad=False,reg=False):
        grad_part_1 = gradient 
        grad_part_2 = self.d_act(self.layer) 
        grad_part_3 = self.input
        grad_middle = grad_part_1 * grad_part_2

        grad = tf.nn.conv2d_backprop_filter(
            input = grad_part_3,
            filter_sizes = self.w.shape,out_backprop = grad_middle,
            strides=[1,stride,stride,1],padding=padding
        )

        grad_pass = tf.nn.conv2d_backprop_input(
            input_sizes = [batch_size_dynamic] + list(grad_part_3.shape[1:]),
            filter= self.w,out_backprop = grad_middle,
            strides=[1,stride,stride,1],padding=padding
        )

        update_w = []
        if  adam:
            update_w.append(
                tf.assign( self.m,self.m*beta1 + (1-beta1) * (grad)   )
            )
            update_w.append(
                tf.assign( self.v_prev,self.v_prev*beta2 + (1-beta2) * (grad ** 2)   )
            )
            m_hat = self.m / (1-beta1)
            v_hat = self.v_prev / (1-beta2)
            adam_middel = learning_rate_change/(tf.sqrt(v_hat) + adam_e)
            adam_middel = tf.multiply(adam_middel,m_hat)
            if reg: adam_middel = adam_middel - learning_rate_change * 0.000001 * self.w
            update_w.append(tf.assign(self.w,tf.subtract(self.w,adam_middel  )) )    

        if awsgrad:
            update_w.append(tf.assign( self.m,self.m*beta1 + (1-beta1) * grad   ))
            v_t = self.v_prev *beta2 + (1-beta2) * grad ** 2 
            def f1(): return v_t
            def f2(): return self.v_hat_prev
            v_max = tf.cond(tf.greater(tf.reduce_sum(v_t), tf.reduce_sum(self.v_hat_prev) ) , true_fn=f1, false_fn=f2)
            adam_middel = tf.multiply(learning_rate_change/(tf.sqrt(v_max) + adam_e),self.m)
            if reg: adam_middel = adam_middel - learning_rate_change * 0.000001 * self.w
            update_w.append(tf.assign(self.w,tf.subtract(self.w,adam_middel  )  ))
            update_w.append(tf.assign( self.v_prev,v_t ))
            update_w.append(tf.assign( self.v_hat_prev,v_max ))        

        if mom:
            update_w.append(tf.assign( self.m,self.m*beta1 + learning_rate* (grad)   ))
            adam_middel = self.m
            if reg: adam_middel = adam_middel - learning_rate_change * 0.000001 * self.w
            update_w.append(tf.assign(self.w,tf.subtract(self.w,adam_middel )) )    

        return grad_pass,update_w  
# # data
PathDicom = "../../../Dataset/cifar-10-batches-py/"
lstFilesDCM = []  # create an empty list
for dirName, subdirList, fileList in os.walk(PathDicom):
    for filename in fileList:
        if not ".html" in filename.lower() and not  ".meta" in filename.lower():  # check whether the file's DICOM
            lstFilesDCM.append(os.path.join(dirName,filename))

# Read the data traind and Test
batch0 = unpickle(lstFilesDCM[0])
batch1 = unpickle(lstFilesDCM[1])
batch2 = unpickle(lstFilesDCM[2])
batch3 = unpickle(lstFilesDCM[3])
batch4 = unpickle(lstFilesDCM[4])

onehot_encoder = OneHotEncoder(sparse=True)
train_batch = np.vstack((batch0[b'data'],batch1[b'data'],batch2[b'data'],batch3[b'data'],batch4[b'data']))
train_label = np.expand_dims(np.hstack((batch0[b'labels'],batch1[b'labels'],batch2[b'labels'],batch3[b'labels'],batch4[b'labels'])).T,axis=1).astype(np.float32)
train_label = onehot_encoder.fit_transform(train_label).toarray().astype(np.float32)

test_batch = unpickle(lstFilesDCM[5])[b'data']
test_label = np.expand_dims(np.array(unpickle(lstFilesDCM[5])[b'labels']),axis=0).T.astype(np.float32)
test_label = onehot_encoder.fit_transform(test_label).toarray().astype(np.float32)

print(train_batch.shape)
print(train_label.shape)
print(test_batch.shape)
trf = ZCA().fit(test_batch)
print(test_label.shape)
print('------------')
train_batch = np.reshape(train_batch,(len(train_batch),3,32,32))
test_batch = np.reshape(test_batch,(len(test_batch),3,32,32))

# reshape data rotate data
train_batch = np.rot90(np.rot90(train_batch,1,axes=(1,3)),3,axes=(1,2))
test_batch = np.rot90(np.rot90(test_batch,1,axes=(1,3)),3,axes=(1,2)).astype(np.float32)

# standardize Normalize data per channel
test_batch[:,:,:,0]  = (test_batch[:,:,:,0] - test_batch[:,:,:,0].mean(axis=0)) / ( test_batch[:,:,:,0].std(axis=0)+ 1e-20)
test_batch[:,:,:,1]  = (test_batch[:,:,:,1] - test_batch[:,:,:,1].mean(axis=0)) / ( test_batch[:,:,:,1].std(axis=0)+ 1e-20)
test_batch[:,:,:,2]  = (test_batch[:,:,:,2] - test_batch[:,:,:,2].mean(axis=0)) / ( test_batch[:,:,:,2].std(axis=0)+ 1e-20)

# print out the data shape
print(train_batch.shape)
print(train_label.shape)
print(test_batch.shape)
print(test_label.shape)

sys.exit()

# hyper parameter
num_epoch = 101  
batch_size = 50
print_size = 1
beta1,beta2,adam_e = 0.9,0.9,1e-9

learning_rate = 0.0002
learnind_rate_decay = 0

proportion_rate = 0.0001
decay_rate = 0

# define class
channel_size = 164
l0 = CNN(3,3,channel_size,tf_elu,d_tf_elu)

l10 = CNN(2,channel_size,channel_size,tf_elu,d_tf_elu)
l1 = CNN(3,channel_size,channel_size,tf_elu,d_tf_elu)
l2 = CNN(3,channel_size,channel_size,tf_elu,d_tf_elu)
l3 = CNN(2,channel_size,channel_size,tf_elu,d_tf_elu)

l40 = CNN(2,channel_size,channel_size,tf_elu,d_tf_elu)
l4 = CNN(3,channel_size,channel_size,tf_elu,d_tf_elu)
l5 = CNN(3,channel_size,channel_size,tf_elu,d_tf_elu)
l6 = CNN(2,channel_size,channel_size,tf_elu,d_tf_elu)

l7 = CNN(3,channel_size,channel_size,tf_elu,d_tf_elu)
l8 = CNN(1,channel_size,channel_size,tf_elu,d_tf_elu)
l9 = CNN(1,channel_size,10,tf_elu,d_tf_elu)

# graph
x = tf.placeholder(shape=[None,32,32,3],dtype=tf.float32)
y = tf.placeholder(shape=[None,10],dtype=tf.float32)

batch_size_dynamic= tf.placeholder(tf.int32, shape=())

iter_variable = tf.placeholder(tf.float32, shape=())
learning_rate_dynamic  = tf.placeholder(tf.float32, shape=())
learning_rate_change = learning_rate_dynamic * (1.0/(1.0+learnind_rate_decay*iter_variable))
decay_dilated_rate   = proportion_rate       * (1.0/(1.0+decay_rate*iter_variable))

droprate1 = tf.placeholder(tf.float32, shape=())
droprate2 = tf.placeholder(tf.float32, shape=())
droprate3 = tf.placeholder(tf.float32, shape=())

layer0 = l0.feedforward(x)

layer10 = l10.feedforward(layer0,stride=2,padding="VALID")
layer1 = l1.feedforward(layer10)
layer2 = l2.feedforward(layer1)
layer3 = l3.feedforward(layer2,stride=2,padding="VALID")

layer40 = l40.feedforward(layer3,stride=2,padding="VALID")
layer4 = l4.feedforward(layer40)
layer5 = l5.feedforward(layer4)
layer6 = l6.feedforward(layer5,stride=2,padding="VALID")

layer7 = l7.feedforward(layer6)
layer8 = l8.feedforward(layer7)
layer9 = l9.feedforward(layer8)

final_global = tf.reduce_mean(layer9,[1,2])
final_soft = tf_softmax(final_global)
cost = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits_v2(logits=final_global,labels=y) )
correct_prediction = tf.equal(tf.argmax(final_soft, 1), tf.argmax(y, 1))
accuracy = tf.reduce_mean(tf.cast(correct_prediction, tf.float32))

# ===== manual ====
grad_prepare = tf.reshape(final_soft-y, [ batch_size_dynamic ,1,1,10] )
grad9,grad9_up = l9.backprop(grad_prepare,learning_rate_change=learning_rate_change,awsgrad=True,batch_size_dynamic=batch_size_dynamic)
grad8,grad8_up = l8.backprop(grad9,learning_rate_change=learning_rate_change,adam=True,batch_size_dynamic=batch_size_dynamic)
grad7,grad7_up = l7.backprop(grad8,learning_rate_change=learning_rate_change,awsgrad=True,batch_size_dynamic=batch_size_dynamic)

# grad6_Input = tf_repeat(grad7,[1,1.4,1.4,1])
grad6,grad6_up = l6.backprop(grad7,learning_rate_change=learning_rate_change,adam=True,batch_size_dynamic=batch_size_dynamic)
grad5,grad5_up = l5.backprop(grad6,learning_rate_change=learning_rate_change,awsgrad=True,batch_size_dynamic=batch_size_dynamic,stride=2)
grad4,grad4_up = l4.backprop(grad5,learning_rate_change=learning_rate_change,adam=True,batch_size_dynamic=batch_size_dynamic)
grad40,grad40_up = l40.backprop(grad4,learning_rate_change=learning_rate_change,awsgrad=True,batch_size_dynamic=batch_size_dynamic)

# grad3_Input = tf_repeat(grad40,[1,2,2,1])
grad3,grad3_up = l3.backprop(grad40,learning_rate_change=learning_rate_change,awsgrad=True,batch_size_dynamic=batch_size_dynamic)
grad2,grad2_up = l2.backprop(grad3,learning_rate_change=learning_rate_change,adam=True,batch_size_dynamic=batch_size_dynamic,stride=2)
grad1,grad1_up = l1.backprop(grad2,learning_rate_change=learning_rate_change,awsgrad=True,batch_size_dynamic=batch_size_dynamic)
grad10,grad10_up = l10.backprop(grad1,learning_rate_change=learning_rate_change,adam=True,batch_size_dynamic=batch_size_dynamic)

grad0,grad0_up = l0.backprop(grad10,learning_rate_change=learning_rate_change,awsgrad=True,batch_size_dynamic=batch_size_dynamic)

grad_update = grad9_up + grad8_up+ grad7_up + \
              grad6_up + grad5_up  + grad4_up + grad40_up + \
              grad3_up + grad2_up  + grad1_up + grad10_up + \
              grad0_up
# ===== manual ====



# sess
with tf.Session() as sess:

    sess.run(tf.global_variables_initializer())
    
    train_cota,train_acca = 0,0
    train_cot,train_acc = [],[]
    
    test_cota,test_acca = 0,0
    test_cot,test_acc = [],[]
    data_input_type = 0 

    for iter in range(num_epoch):

        train_batch,train_label = shuffle(train_batch,train_label)

        lower_bound = 0.025 * (iter+1)/num_epoch
        random_drop1 = np.random.uniform(low=0.975+lower_bound,high=1.000000000000001)
        random_drop2 = np.random.uniform(low=0.975+lower_bound,high=1.000000000000001)
        random_drop3 = np.random.uniform(low=0.975+lower_bound,high=1.000000000000001)

        for batch_size_index in range(0,len(train_batch),batch_size//2):
            current_batch = train_batch[batch_size_index:batch_size_index+batch_size//2]
            current_batch_label = train_label[batch_size_index:batch_size_index+batch_size//2]

            images_aug = seq.augment_images(current_batch.astype(np.float32))
            current_batch = np.vstack((current_batch,images_aug)).astype(np.float32)
            current_batch_label = np.vstack((current_batch_label,current_batch_label)).astype(np.float32)
            input_sess_array = [cost,accuracy,correct_prediction,grad_update]
            input_feed_dict={x:current_batch,y:current_batch_label,
            iter_variable:iter,learning_rate_dynamic:learning_rate,droprate1:1.0,droprate2:1.0,droprate3:0.9,batch_size_dynamic:batch_size}
                
            # online data augmentation here and standard normalization
            current_batch[:,:,:,0]  = (current_batch[:,:,:,0] - current_batch[:,:,:,0].mean(axis=0)) / ( current_batch[:,:,:,0].std(axis=0)+ 1e-20)
            current_batch[:,:,:,1]  = (current_batch[:,:,:,1] - current_batch[:,:,:,1].mean(axis=0)) / ( current_batch[:,:,:,1].std(axis=0)+ 1e-20)
            current_batch[:,:,:,2]  = (current_batch[:,:,:,2] - current_batch[:,:,:,2].mean(axis=0)) / ( current_batch[:,:,:,2].std(axis=0)+ 1e-20)
            # current_batch[:,:,:,0]  = (current_batch[:,:,:,0] - current_batch[:,:,:,0].min(axis=0)) / (current_batch[:,:,:,0].max(axis=0) - current_batch[:,:,:,0].min(axis=0)) 
            # current_batch[:,:,:,1]  = (current_batch[:,:,:,1] - current_batch[:,:,:,1].min(axis=0)) / (current_batch[:,:,:,1].max(axis=0) - current_batch[:,:,:,1].min(axis=0)) 
            # current_batch[:,:,:,2]  = (current_batch[:,:,:,2] - current_batch[:,:,:,2].min(axis=0)) / (current_batch[:,:,:,2].max(axis=0) - current_batch[:,:,:,2].min(axis=0)) 
            current_batch,current_batch_label  = shuffle(current_batch,current_batch_label)
            # online data augmentation here and standard normalization

            sess_result = sess.run(input_sess_array,feed_dict=input_feed_dict  )
            print("Current Iter : ",iter, " current batch: ",batch_size_index, ' Current cost: ', sess_result[0],
            ' Current Acc: ', sess_result[1],end='\r')
            train_cota = train_cota + sess_result[0]
            train_acca = train_acca + sess_result[1]
            
        for test_batch_index in range(0,len(test_batch),batch_size):
            current_batch = test_batch[test_batch_index:test_batch_index+batch_size]
            current_batch_label = test_label[test_batch_index:test_batch_index+batch_size]
            sess_result = sess.run([cost,accuracy,correct_prediction],
            feed_dict={x:current_batch,y:current_batch_label,iter_variable:iter,learning_rate_dynamic:learning_rate,
            droprate1:1.0,droprate2:1.0,droprate3:1.0,batch_size_dynamic:batch_size})
            print("Current Iter : ",iter, " current batch: ",test_batch_index, ' Current cost: ', sess_result[0],
            ' Current Acc: ', sess_result[1],end='\r')
            test_acca = sess_result[1] + test_acca
            test_cota = sess_result[0] + test_cota

        if iter % print_size==0:
            print("\n---------- Learning Rate : ", learning_rate * (1.0/(1.0+learnind_rate_decay*iter))," Data: ",data_input_type )
            
            print('Train Current cost: ', train_cota/(len(train_batch)/(batch_size//2)),' Current Acc: ', 
            train_acca/(len(train_batch)/(batch_size//2) ),end='\n')

            print('Test Current cost: ', test_cota/(len(test_batch)/batch_size),' Current Acc: ', 
            test_acca/(len(test_batch)/batch_size),end='\n')
            print("----------")

        train_acc.append(train_acca/(len(train_batch)/batch_size//2))
        train_cot.append(train_cota/(len(train_batch)/batch_size//2))
        test_acc.append(test_acca/(len(test_batch)/batch_size))
        test_cot.append(test_cota/(len(test_batch)/batch_size))
        test_cota,test_acca = 0,0
        train_cota,train_acca = 0,0

    # Normalize the cost of the training
    train_cot = (train_cot-min(train_cot) ) / (max(train_cot)-min(train_cot))
    test_cot = (test_cot-min(test_cot) ) / (max(test_cot)-min(test_cot))

    # training done now plot
    plt.figure()
    plt.plot(range(len(train_acc)),train_acc,color='red',label='acc ovt')
    plt.plot(range(len(train_cot)),train_cot,color='green',label='cost ovt')
    plt.legend()
    plt.title("Train Average Accuracy / Cost Over Time")
    plt.savefig("Case a Train.png")

    plt.figure()
    plt.plot(range(len(test_acc)),test_acc,color='red',label='acc ovt')
    plt.plot(range(len(test_cot)),test_cot,color='green',label='cost ovt')
    plt.legend()
    plt.title("Test Average Accuracy / Cost Over Time")
    plt.savefig("Case a Test.png")





# -- end code --