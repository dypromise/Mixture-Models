# -*- coding: utf-8 -*-

import numpy as np
from scipy.stats import multivariate_normal as mvn
from sklearn.cluster import KMeans

class MDA(object):
    '''
    Mixture Discriminant Analysis - generative method of classification
    
    A classifier with non-linear decision boundary , generated by fitting class
    conditional densities with mixture of Gaussians. And using class conditional 
    densities to obtain posterior distribution, using Bayes rule. 
    
    [n = n_samples, m = n_features]
    
    Parameters:
    ------------
    
    Y :  numpy array, shape = [n,1]
           Target Values
          
    X :  numpy array of size 'n x m'
           Expanatory variables
          
    clusters :  list of lentgh 'n' 
           Number of mixture components in each class
          
    init_restarts : int , default = 2
           Number of restarts during parameter initialisation
          
    k : int 
           Number of classes
           
    init_conv_threshold: float, default = 1e-5 
           Convergence threshold for k-means in intialisation step
           
    iter_conv_threshold: float, default = 1e-5
           Convergence threshold for EM algorithm that fits MDA
           
    max_iter_init: int, default = 300
           Maximum number of iterations for k-means on initialisation step
         
    max_iter : int, default = 300
           Maximum number of iterations for EM algorithm
           
    accuracy: float, default = 1e-5
           Level of accuracy, for preventing numerical underflow
    '''
    
    def __init__(self,gt,X,clusters,k, max_iter_init = 300, init_restarts       = 2, 
                                                          init_conv_theshold  = 1e-5,
                                                          iter_conv_threshold = 1e-20,
                                                          max_iter            = 300,
                                                          verbose             = True,
                                                          accuracy            = 1e-5):
                                                              
        self.Y                   =  gt
        self.X                   =  X
        # n - observations; m - dimension  
        self.n, self.m           =  np.shape(X)                
        self.k                   =  k
        # k - number of classes                         
        self.clusters            =  clusters                  
        self.class_prior         =  np.zeros(self.m)
        # mixing pro
        self.latent_var_prior    =  [np.ones(clusters[i])/clusters[i] for i in range(self.k)] 
        self.freq                =  np.sum(self.Y, axis = 0)  # number of elements in each class
        # pooled covariance matrix
        self.covar               =  np.eye(self.m)            
        # means
        self.mu                  =  [np.zeros([self.m,clusters[i]]) for i in range(self.k)]
        # responsibilities
        self.responsibilities    =  [0.001*np.zeros([self.n,clusters[i]]) for i in range(self.k)]
        # list of lower bounds (expected to be non-increasing series)
        self.lower_bounds        =  []                             
        self.kmeans_maxiter      =  max_iter_init
        self.kmeans_retsarts     =  init_restarts
        self.max_iter            =  max_iter
        self.kmeans_theshold     =  init_conv_theshold
        self.mda_threshold       =  iter_conv_threshold
        self.verbose             =  verbose
        self.accuracy            =  accuracy
        
        
    def train(self):
        '''
        Train model
        '''
        self._initialise_params()
        self._iterate()
        
    def posterior_probs(self):
        ''' 
        Calculates posterior probability
        '''
        posterior = np.zeros([self.n,self.k])
        
        for k,cluster in enumerate(self.clusters):
            class_prob = np.zeros(self.n)
            for j in range(cluster):
                p          = self.bounded_variable(mvn.pdf(self.X,self.mu[k][:,j],self.covar),self.accuracy,1-self.accuracy)
                class_prob += p*self.latent_var_prior[k][j]
            posterior[:,k] = class_prob*self.class_prior[k]
        posterior /= np.outer(np.sum(posterior,axis = 1), np.ones(self.k))
        return posterior
        
        
        
    def _initialise_params(self):
        '''
        Initialises parameters using k-means to calculate responsibilities
        '''
        
        # initialise class priors
        self._class_prior_compute()
        
        # calculate responsibilities using k-means results      
        for i,cluster in enumerate(self.clusters):
            kmeans = KMeans(n_clusters = cluster, 
                            max_iter    = self.kmeans_maxiter,
                            init       = "k-means++",
                            tol        = self.kmeans_theshold)
            kmeans.fit(self.X[self.Y[:,i]==1,:])
            prediction = kmeans.predict(self.X[self.Y[:,i]==1,:])
            for j in range(cluster):
                self.responsibilities[i][self.Y[:,i]==1,j] = 1*(prediction==j)
                
        # initialise parameters of mda through M-step
        self._m_step()
        if self.verbose:
            print "Initialization step complete"
            

    def _iterate(self):
        ''' 
        Iterates between E-step and M-step, untill change in likelihood is smaller
        than threshold
        '''
        delta = 1
        for i in range(self.max_iter):
            self._e_step_lower_bound_likelihood()
            if len(self.lower_bounds) >= 2:
                delta_change = float(self.lower_bounds[-1] - self.lower_bounds[-2])
                delta        = delta_change/abs(self.lower_bounds[-2])
                
            # if change in lower bound for likelihood is larger than threshold continue EM algorithm
            if delta > self.mda_threshold:
                self._m_step()
                if self.verbose:
                    iteration_verbose = "iteration {0} completed, lower bound of log-likelihood is {1} "
                    print iteration_verbose.format(i,self.lower_bounds[-1])
            else:
                print "algorithm converged"
                break
        
        
    def _e_step_lower_bound_likelihood(self):
        '''
        Calculates posterior distribution of latent variable for each class
        and lower bound for log-likelihood of data
        '''
        lower_bound = 0.0
        for i,resp_k in enumerate(self.responsibilities):
            for j in range(self.clusters[i]):
                # bound value of pdf to prevent underflow
                prior            = self.bounded_variable(mvn.pdf(self.X,self.mu[i][:,j],self.covar),self.accuracy,1-self.accuracy)
                weighting        = self.Y[:,i] * resp_k[:,j]
                w                =  weighting*np.log(prior) + weighting*np.log(self.latent_var_prior[i][j])
                lower_bound     += np.sum(w)
                # responsibilities for latent variable corresponding to class k
                resp_k[:,j]      = prior*self.latent_var_prior[i][j]
            normaliser = np.sum(resp_k, axis = 1)
            resp_k    /= np.outer(normaliser,np.ones(self.clusters[i]))
        self.lower_bounds.append(lower_bound)
        
        
    def _m_step(self):
        '''
        M-step of Expectation Maximization Algorithm
        
        Calculates maximum likelihood estimates of class priors, mixing latent var.
        probabilities, means and pooled covariance matrix/
        '''
        covar = np.zeros([self.m,self.m])
        for i in range(self.k):
            for j in range(self.clusters[i]):
                
                # calculate mixing probabilities
                class_indicator               = self.Y[:,i]*self.responsibilities[i][:,j]
                self.latent_var_prior[i][j]   = np.sum(class_indicator)/self.freq[i]
    
                # calculate means
                weighted_means                = np.sum(np.dot(X.T, np.diagflat(class_indicator)), axis=1)
                self.mu[i][:,j]               = weighted_means / np.sum(class_indicator)
                
                # calculate pooled covariance matrix
                centered                      = self.X - np.outer(self.mu[i][:,j],np.ones(self.n)).T
                addition                      = np.dot(np.dot(centered.T, np.diagflat(class_indicator)),centered)
                covar                        += addition
                
        self.covar = covar/self.n


    def _class_prior_compute(self):
        ''' 
        Computes prior probability of observation being in particular class 
        '''
        self.class_prior = self.freq/np.sum(self.freq)       
        
#--------------------- Helper Methods --------------------------------------------#
    
    
    @staticmethod
    def bounded_variable(x,lo,hi):
        '''
        Returns 'x' if 'x' is between 'lo' and 'hi', 'hi' if x is larger than 'hi'
        and 'lo' if x is lower than 'lo'
        '''
        x[x>hi]=hi
        x[x<lo]=lo
        return x
        
        
            
        
        
if __name__=="__main__":
    X = np.random.normal(0,0.2,[24,2])
    X[0:6,0] = np.random.normal(2,0.2,6)
    X[0:6,1] = np.random.normal(2,0.2,6)
    X[6:12,0] = np.random.normal(3,0.2,6)
    X[6:12,1] = np.random.normal(4,0.2,6)
    X[12:18,:]  = np.random.normal(0,0.2,[6,2])
    X[18:24,:]  = np.random.normal(-4,0.2,[6,2])
    #X[0:12,:] = np.random.normal(0,1,[12,2])
    #X[12:24,:] = np.random.normal(4,1,[12,2])
    Y = np.zeros([24,2])
    Y[0:12,0] = 1
    Y[12:24,1] = 1
    mda = MDA(Y,X,[2,2],2)
    mda.train()
    posterior = mda.posterior_probs()
    
    
    
    
    