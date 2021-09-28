# -*- coding: utf-8 -*-
"""Autoregressive model for multivariate time series outlier detection.
"""
import numpy as np
from sklearn.utils import check_array
from sklearn.utils.validation import check_is_fitted
from sklearn.utils import column_or_1d

from .CollectiveBase import CollectiveBaseDetector
from combo.models.score_comb import average, maximization, median, aom, moa
from combo.utils.utility import standardizer

from .AutoRegOD import AutoRegOD
from .utility import get_sub_sequences_length


class MultiAutoRegOD(CollectiveBaseDetector):
    """Autoregressive models use linear regression to calculate a sample's
    deviance from the predicted value, which is then used as its
    outlier scores. This model is for multivariate time series.
    This model handles multivariate time series by various combination 
    approaches. See AutoRegOD for univarite data. 
    
    See :cite:`aggarwal2015outlier,zhao2020using` for details.

    Parameters
    ----------
    window_size : int
        The moving window size.

    step_size : int, optional (default=1)
        The displacement for moving window.

    contamination : float in (0., 0.5), optional (default=0.1)
        The amount of contamination of the data set, i.e.
        the proportion of outliers in the data set. When fitting this is used
        to define the threshold on the decision function.

    method : str, optional (default='average')
        Combination method: {'average', 'maximization',
        'median'}. Pass in weights of detector for weighted version.
        
    weights : numpy array of shape (1, n_dimensions)
        Score weight by dimensions.

    Attributes
    ----------
    decision_scores_ : numpy array of shape (n_samples,)
        The outlier scores of the training data.
        The higher, the more abnormal. Outliers tend to have higher
        scores. This value is available once the detector is
        fitted.

    labels_ : int, either 0 or 1
        The binary labels of the training data. 0 stands for inliers
        and 1 for outliers/anomalies. It is generated by applying
        ``threshold_`` on ``decision_scores_``.
    """

    def __init__(self, window_size, step_size=1, method='average',
                 weights=None, contamination=0.1):
        super(MultiAutoRegOD, self).__init__(contamination=contamination)
        self.window_size = window_size
        self.step_size = step_size
        self.method = method
        self.weights = weights

    def _validate_weights(self):
        """Internal function for validating and adjust weights.

        Returns
        -------

        """
        if self.weights is None:
            self.weights = np.ones([1, self.n_models_])
        else:
            self.weights = column_or_1d(self.weights).reshape(
                1, len(self.weights))
            assert (self.weights.shape[1] == self.n_models_)

            # adjust probability by a factor for integrity
            adjust_factor = self.weights.shape[1] / np.sum(self.weights)
            self.weights = self.weights * adjust_factor

    def _fit_univariate_model(self, X):
        """Internal function for fitting one dimensional ts.
        """
        X = check_array(X)
        n_samples, n_sequences = X.shape[0], X.shape[1]

        models = []

        # train one model for each dimension        
        for i in range(n_sequences):
            models.append(AutoRegOD(window_size=self.window_size,
                                    step_size=self.step_size,
                                    contamination=self.contamination))
            models[i].fit(X[:, i].reshape(-1, 1))

        return models

    def _score_combination(self, scores): # pragma: no cover
        """Internal function for combining univarite scores.
        """

        # combine by different approaches
        if self.method == 'average':
            return average(scores, estimator_weights=self.weights)
        if self.method == 'maximization':
            return maximization(scores)
        if self.method == 'median':
            return median(scores)

    def fit(self, X: np.array) -> object:
        """Fit detector. y is ignored in unsupervised methods.

        Parameters
        ----------
        X : numpy array of shape (n_samples, n_features)
            The input samples.

        y : Ignored
            Not used, present for API consistency by convention.

        Returns
        -------
        self : object
            Fitted estimator.
        """
        X = check_array(X).astype(np.float)

        # fit each dimension individually
        self.models_ = self._fit_univariate_model(X)
        self.valid_len_ = self.models_[0].valid_len_
        self.n_models_ = len(self.models_)

        # assign the left and right inds, same for all models
        self.left_inds_ = self.models_[0].left_inds_
        self.right_inds_ = self.models_[0].right_inds_

        # validate and adjust weights
        self._validate_weights()

        # combine the scores from all dimensions
        self._decison_mat = np.zeros([self.valid_len_, self.n_models_])
        for i in range(self.n_models_):
            self._decison_mat[:, i] = self.models_[i].decision_scores_

        # scale scores by standardization before score combination
        self._decison_mat_scalaled, self._score_scalar = standardizer(
            self._decison_mat, keep_scalar=True)

        self.decision_scores_ = self._score_combination(
            self._decison_mat_scalaled)

        self._process_decision_scores()
        return self

    def decision_function(self, X: np.array):
        """Predict raw anomaly scores of X using the fitted detector.

        The anomaly score of an input sample is computed based on the fitted
        detector. For consistency, outliers are assigned with
        higher anomaly scores.

        Parameters
        ----------
        X : numpy array of shape (n_samples, n_features)
            The input samples. Sparse matrices are accepted only
            if they are supported by the base estimator.

        Returns
        -------
        anomaly_scores : numpy array of shape (n_samples,)
            The anomaly score of the input samples.
        """
        check_is_fitted(self, ['models_'])
        X = check_array(X).astype(np.float)
        assert (X.shape[1] == self.n_models_)
        n_samples = len(X)

        # need to subtract 1 because need to have y for subtraction
        valid_len = get_sub_sequences_length(n_samples, self.window_size,
                                             self.step_size) - 1

        # combine the scores from all dimensions
        decison_mat = np.zeros([valid_len, self.n_models_])
        for i in range(self.n_models_):
            decison_mat[:, i], X_left_inds, X_right_inds = \
                self.models_[i].decision_function(X[:, i].reshape(-1, 1))

        # scale the decision mat
        decison_mat_scaled = self._score_scalar.transform(decison_mat)
        decision_scores = self._score_combination(decison_mat_scaled)
        decision_scores = np.append(decision_scores, min(decision_scores))

        return decision_scores, X_left_inds, X_right_inds


if __name__ == "__main__": # pragma: no cover
    X_train = np.asarray(
        [[3., 5], [5., 9], [7., 2], [42., 20], [8., 12], [10., 12], [12., 12],
         [18., 16], [20., 7], [18., 10], [23., 12], [22., 15]])

    X_test = np.asarray(
        [[3., 5], [5., 9], [7., 2], [42., 20], [8., 12], [10., 12], [12., 12],
         [18., 16], [20., 7], [18., 10], [23., 12], [22., 15]])

    # X_test = np.asarray(
    #     [[12., 10], [8., 12], [80., 80], [92., 983],
    #      [18., 16], [20., 7], [18., 10], [3., 5], [5., 9], [23., 12],
    #      [22., 15]])

    clf = MultiAutoRegOD(window_size=3, step_size=1, contamination=0.2)

    clf.fit(X_train)
    decision_scores, left_inds_, right_inds = clf.decision_scores_, \
                                              clf.left_inds_, clf.right_inds_
    print(clf.left_inds_, clf.right_inds_)
    pred_scores, X_left_inds, X_right_inds = clf.decision_function(X_test)
    pred_labels, X_left_inds, X_right_inds = clf.predict(X_test)
    pred_probs, X_left_inds, X_right_inds = clf.predict_proba(X_test)

    print(pred_scores)
    print(pred_labels)
    print(pred_probs)
