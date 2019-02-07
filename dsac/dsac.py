import torch
import torch.nn.functional as F

import random
import utils
import numpy as np
np.set_printoptions(precision=4)
np.set_printoptions(suppress=True)

class DSAC:
	'''
	Differentiable RANSAC to robustly fit lines.
	'''

	def __init__(self, hyps, inlier_thresh, inlier_beta, inlier_alpha, loss_function):
		'''
		Constructor.

		hyps -- number of line hypotheses sampled for each image
		inlier_thresh -- threshold used in the soft inlier count, its measured in relative image size (1 = image width)
		inlier_beta -- scaling factor within the sigmoid of the soft inlier count
		inlier_alpha -- scaling factor for the soft inlier scores (controls the peakiness of the hypothesis distribution)
		loss_function -- function to compute the quality of estimated line parameters wrt ground truth
		'''

		self.hyps = hyps
		self.inlier_thresh = inlier_thresh
		self.inlier_beta = inlier_beta
		self.inlier_alpha = inlier_alpha
		self.loss_function = loss_function

	def __sample_hyp(self, X, Y):
		'''
		Calculate an H hypothesis from 4 random correspondences.

		X: [N, 2]
		Y: [N, 2]
		'''

		# select 4 random correspomndences
		idx = random.sample(range(self.N), 5)
		# idx = [0, 1, 2, 3]
		# print(idx)
		X_4 = X[idx, :]
		Y_4 = Y[idx, :]

		return utils.H_from_XY(X_4, Y_4), idx

	def __soft_inlier_count(self, H, X, Y):
		'''
		Soft inlier count for a given line and a given set of points.

		slope -- slope of the line
		intercept -- intercept of the line
		x -- vector of x values
		y -- vector of y values
		'''

		# point line distances
		HX = utils.de_homo_py(torch.matmul(H, utils.homo_py(X).t()).t())
		dists = torch.norm(Y - HX, dim=1)
		# print(dists.detach().numpy())
		# print(np.max(dists.detach().numpy()))

		# soft inliers
		dists = 1 - torch.sigmoid(self.inlier_beta * (dists - self.inlier_thresh)) 
		# print(dists.detach().numpy())
		score = torch.sum(dists)

		return score, dists

	# def __refine_hyp(self, x, y, weights):
	# 	'''
	# 	Refinement by weighted Deming regression.

	# 	Fits a line minimizing errors in x and y, implementation according to: 
	# 		'Performance of Deming regression analysis in case of misspecified 
	# 		analytical error ratio in method comparison studies'
	# 		Kristian Linnet, in Clinical Chemistry, 1998

	# 	x -- vector of x values
	# 	y -- vector of y values
	# 	weights -- vector of weights (1 per point)		
	# 	'''

	# 	ws = weights.sum()
	# 	xm = (x * weights).sum() / ws
	# 	ym = (y * weights).sum() / ws

	# 	u = (x - xm)**2
	# 	u = (u * weights).sum()

	# 	q = (y - ym)**2
	# 	q = (q * weights).sum()

	# 	p = torch.mul(x - xm, y - ym)
	# 	p = (p * weights).sum()

	# 	slope = (q - u + torch.sqrt((u - q)**2 + 4*p*p)) / (2*p)
	# 	intercept = ym - slope * xm

	# 	return slope, intercept

		

	def __call__(self, X, Y, H):
		'''
		Perform robust, differentiable line fitting according to DSAC.

		Returns the expected loss of choosing a good line hypothesis which can be used for backprob.

		prediction -- predicted 2D points for a batch of images, array of shape (Bx2) where
			B is the number of images in the batch
			2 is the number of point dimensions (y, x)
		labels -- ground truth labels for the batch, array of shape (Bx2) where
			B is the number of images in the batch
			2 is the number of parameters (intercept, slope)
		'''

		# working on CPU because of many, small matrices
		X = X.cpu()
		Y = Y.cpu()
		H = H.cpu()

		self.N = X.size(0)
		assert X.size(0) == Y.size(0), 'N mismatch between X and Y!'

		avg_exp_loss = 0 # expected loss
		avg_top_loss = 0 # loss of best hypothesis

		# self.est_parameters = torch.zeros(batch_size, 2) # estimated lines
		self.est_losses = torch.zeros(1) # loss of estimated lines
		self.inliers = torch.zeros(self.N) # (soft) inliers for estimated lines

		# hyp_losses = torch.zeros([self.hyps, 1]) # loss of each hypothesis
		hyp_scores = torch.zeros([self.hyps, 1]) # score of each hypothesis

		self.max_score = 0 	# score of best hypothesis

		# y = prediction[b, 0] # all y-values of the prediction
		# x = prediction[b, 1] # all x.values of the prediction

		N_scores = torch.zeros([self.N, 1])
		N_counts = torch.zeros([self.N, 1])

		for h in range(self.hyps):	

			# === step 1: sample hypothesis ===========================
			H, idx = self.__sample_hyp(X, Y)

			# === step 2: score hypothesis using soft inlier count ====
			score, dists = self.__soft_inlier_count(H, X, Y)

			# === step 3: refine hypothesis ===========================
			# slope, intercept = self.__refine_hyp(x, y, dists)

			# hyp = torch.zeros([2])
			# hyp[1] = slope
			# hyp[0] = intercept

			# === step 4: calculate loss of hypothesis ================
			# loss = self.loss_function(X, Y, H) 

			# store results
			# hyp_losses[h] = loss
			hyp_scores[h] = score

			N_scores[idx] += score
			# print(N_scores)
			N_counts[idx] += 1.

			# keep track of best hypothesis so far
			if score > self.max_score:
				self.max_score = score
				# self.est_losses[b] = loss
				# self.est_parameters[b] = hyp
				self.best_H = H
				self.best_4_idx = idx
				# self.batch_inliers[b] = inliers

		# # === step 5: calculate the expectation ===========================

		# #softmax distribution from hypotheses scores			
		# hyp_scores = F.softmax(self.inlier_alpha * hyp_scores, 0)

		# # expectation of loss
		# exp_loss = torch.sum(hyp_losses * hyp_scores)
		# avg_exp_loss = avg_exp_loss + exp_loss

		# # loss of best hypothesis (for evaluation)
		# avg_top_loss = avg_top_loss + self.est_losses[b]
	
		# return avg_exp_loss / batch_size, avg_top_loss / batch_size
		
		return N_scores / (N_counts+1e-10)