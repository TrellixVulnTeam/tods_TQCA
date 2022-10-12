from ray import tune
import ray
import uuid
import random

from d3m.metadata.pipeline import Pipeline

from axolotl.algorithms.base import PipelineSearchBase
from axolotl.utils import  schemas as schemas_utils


import pandas as pd
import numpy as np
from tods import schemas as schemas_utils
from tods import generate_dataset, evaluate_pipeline

import os

import argparse

from d3m import index
from d3m.metadata.base import ArgumentType
from d3m.metadata.pipeline import Pipeline, PrimitiveStep
from axolotl.backend.simple import SimpleRunner
from tods import generate_dataset, generate_problem

from tods import generate_dataset, load_pipeline, evaluate_pipeline
from tods import generate_dataset, evaluate_pipeline, fit_pipeline, load_pipeline, produce_fitted_pipeline, load_fitted_pipeline, save_fitted_pipeline, fit_pipeline
import pdb

@ray.remote
class GlobalStats:
  def __init__(self):
    self.fitted_pipeline_list = []
    self.pipeline_description_list = []
    self.scores = []

  def append_fitted_pipeline_id(self, val):
    self.fitted_pipeline_list.append(val)

  def append_pipeline_description(self, description):
    self.pipeline_description_list.append(description.to_json())

  def append_score(self, score):
    self.scores.append(score)

  def get_fitted_pipeline_list(self):
    return self.fitted_pipeline_list
  
  def get_pipeline_description_list(self):
    return self.pipeline_description_list

  def get_scores(self):
    return self.scores


class HyperSearcher():
  def __init__(self, dataset, metric):
    ray.init(local_mode=True, ignore_reinit_error=True)
    self.dataset = dataset
    self.metric = metric
    self.stats = GlobalStats.remote()

  def search(self, search_space, config):
    if config["searching_algorithm"] == "random":
      from ray.tune.suggest.basic_variant import BasicVariantGenerator
      searcher = BasicVariantGenerator() #Random/Grid Searcher
    elif config["searching_algorithm"] == "hyperopt":
      from ray.tune.suggest.hyperopt import HyperOptSearch
      searcher = HyperOptSearch(max_concurrent=2, metric="RECALL") #HyperOpt Searcher
    elif config["searching_algorithm"] == "zoopt":
      zoopt_search_config = {
        "parallel_num": 64,  # how many workers to parallel
      }
      from ray.tune.suggest.zoopt import ZOOptSearch
      searcher = ZOOptSearch(budget=20, **zoopt_search_config)
    elif config["searching_algorithm"] == "skopt":
      from ray.tune.suggest.skopt import SkOptSearch
      searcher = SkOptSearch()
    elif config["searching_algorithm"] == "nevergrad":
      import nevergrad as ng
      from ray.tune.suggest.nevergrad import NevergradSearch
      searcher = NevergradSearch(
        optimizer=ng.optimizers.OnePlusOne)
    else:
      raise ValueError("Searching algorithm not supported.")

    import multiprocessing
    num_cores =  multiprocessing.cpu_count()

    # from ray.tune.schedulers import AsyncHyperBandScheduler
    # scheduler = AsyncHyperBandScheduler(grace_period=10, max_t=100, metric="RECALL")

    # from ray.tune.schedulers import HyperBandScheduler
    # scheduler = HyperBandScheduler(max_t=100, metric="RECALL")

    # from ray.tune.schedulers import MedianStoppingRule
    # scheduler = MedianStoppingRule(grace_period=60, metric="RECALL")

    # from ray.tune.schedulers import PopulationBasedTraining
    # scheduler = PopulationBasedTraining(
    #     time_attr='time_total_s',
    #     metric='RECALL',
    #     perturbation_interval=600.0)

    # from ray.tune.schedulers.pb2 import PB2
    # scheduler = PB2(
    #     time_attr='time_total_s',
    #     metric='RECALL',
    #     perturbation_interval=600.0,
    #     hyperparam_bounds={
    #         "lr": [1e-3, 1e-5],
    #         "alpha": [0.0, 1.0],
    #     ...
    #     })
    # pip install GPy sklearn
    # this one doesnt work and this needs hyperparam_bounds

    # from ray.tune.schedulers import HyperBandForBOHB
    # scheduler = HyperBandForBOHB(max_t=100, metric="RECALL")
    # this one doesnt work



    from ray.tune.suggest.bayesopt import BayesOptSearch
    seacher = BayesOptSearch()

    # from ray.tune.suggest.ax import AxSearch
    # seacher = AxSearch(metric="RECALL")
    # the search space doesn't satisfy

    # from ray.tune.suggest.flaml import B  lendSearch
    # searcher = BlendSearch(metric="RECALL")
    # package dependency issue, same for cfo

    # from ray.tune.suggest.dragonfly import DragonflySearch
    # seacher = DragonflySearch()

    # from ray.tune.suggest.hebo import HEBOSearch
    # seacher = HEBOSearch(metric="RECALL")
    # error

    # import nevergrad as ng
    # from ray.tune.suggest.nevergrad import NevergradSearch
    # seacher = NevergradSearch(
    #   optimizer=ng.optimizers.OnePlusOne,
    # metric="RECALL")

    # import optuna
    # space = {
    #   "a": optuna.distributions.UniformDistribution(6, 8),
    #   "b": optuna.distributions.LogUniformDistribution(1e-4, 1e-2),
    # }
    # from ray.tune.suggest.optuna import OptunaSearch
    # seacher = OptunaSearch()
    # the serch space doesn't satisfy

    # from ray.tune.suggest.sigopt import SigOptSearch
    # seacher = SigOptSearch(metric="RECALL")
    # error

    # from ray.tune.suggest.skopt import SkOptSearch
    # seacher = SkOptSearch(metric="RECALL")

    # zoopt_search_config = {
    #   "parallel_num": 8,  # how many workers to parallel
    # }

    # from ray.tune.suggest.zoopt import ZOOptSearch
    # seacher = ZOOptSearch(metric="RECALL", budget=20, **zoopt_search_config)








    analysis = ray.tune.run(
      self._evaluate,
      metric = "RECALL",
      config = search_space,
      num_samples = config["num_samples"],
      # resources_per_trial = {"cpu": num_cores, "gpu": 1},
      resources_per_trial={"cpu": 3, "gpu": 1},
      mode = config["mode"]
      # search_alg = seacher
      # name = config["searching_algorithm"] + "_" + str(config["num_samples"])
      # scheduler=scheduler
    )

    best_config = analysis.get_best_config(metric="RECALL")

    df = analysis.results_df
    df = analysis.dataframe(metric="RECALL", mode="min")
    print(df)
    df.to_csv('out.csv')  

    best_config_pipeline_id = self.find_best_pipeline_id(best_config, df)

    return best_config, best_config_pipeline_id

  def _evaluate(self, search_space):
    pipeline = self.build_pipeline(search_space)

    fitted_pipeline = fit_pipeline(self.dataset, pipeline, self.metric)

    fitted_pipeline_id = save_fitted_pipeline(fitted_pipeline)

    self.stats.append_fitted_pipeline_id.remote(fitted_pipeline_id)

    self.stats.append_pipeline_description.remote(pipeline)

    pipeline_result = evaluate_pipeline(self.dataset, pipeline, self.metric)

    score = pipeline_result.scores.value[0]

    self.stats.append_score.remote(score)

    # ray.tune.report(score = score * 100)
    # ray.tune.report(accuracy=1)

    from random import seed
    from random import random
    from datetime import datetime
    seed(datetime.now())

    # import random
    # from datetime import datetime
    # temp = random.seed(datetime.now())

    temp = random()

    yield {"F1_MACRO": pipeline_result.scores.value[2],
    "RECALL": pipeline_result.scores.value[1],
    "PRECISION": pipeline_result.scores.value[0],
    "F1": pipeline_result.scores.value[3]
    # "recall": 
    }

    # tune.report()

  def build_pipeline(self, search_space):
    from d3m import index
    from d3m.metadata.base import ArgumentType
    from d3m.metadata.pipeline import Pipeline, PrimitiveStep
    import sys

    primitive_map = {'axiswise_scaler': 'transformation',
    'standard_scaler': 'transformation',
    'power_transformer': 'transformation',
    'quantile_transformer': 'transformation',
    'moving_average_transform': 'transformation',
    'simple_exponential_smoothing': 'transformation',
    'holt_smoothing': 'transformation',
    'holt_winters_exponential_smoothing': 'transformation',
    'time_series_seasonality_trend_decomposition': 'decomposition',
    'subsequence_segmentation': ''
    }







    pipeline_description = Pipeline()
    pipeline_description.add_input(name='inputs')

    counter = 0

    # Step 0: dataset_to_dataframe
    step_0 = PrimitiveStep(primitive=index.get_primitive('d3m.primitives.tods.data_processing.dataset_to_dataframe'))
    step_0.add_argument(name='inputs', argument_type=ArgumentType.CONTAINER, data_reference='inputs.0')
    step_0.add_output('produce')
    pipeline_description.add_step(step_0)
    counter += 1

    # Step 1: column_parser
    step_1 = PrimitiveStep(primitive=index.get_primitive('d3m.primitives.tods.data_processing.column_parser'))
    step_1.add_argument(name='inputs', argument_type=ArgumentType.CONTAINER, data_reference='steps.0.produce')
    step_1.add_output('produce')
    pipeline_description.add_step(step_1)
    counter += 1

    # Step 2: extract_columns_by_semantic_types(attributes)
    step_2 = PrimitiveStep(primitive=index.get_primitive('d3m.primitives.tods.data_processing.extract_columns_by_semantic_types'))
    step_2.add_argument(name='inputs', argument_type=ArgumentType.CONTAINER, data_reference='steps.1.produce')
    step_2.add_output('produce')
    step_2.add_hyperparameter(name='semantic_types', argument_type=ArgumentType.VALUE,
                    data=['https://metadata.datadrivendiscovery.org/types/Attribute'])
    pipeline_description.add_step(step_2)
    counter += 1







    # if 'timeseries_processing' in search_space.keys():
    #   timeseries_processing_list = []

    #   timeseries_processing = search_space.pop('timeseries_processing', None)
    #   if ' ' in timeseries_processing:
    #     timeseries_processing_list = timeseries_processing.split(' ')
    #   else:
    #     timeseries_processing_list.append(timeseries_processing)

    #   for x in range(len(timeseries_processing_list)):
    #     this = sys.modules[__name__]
    #     name = 'step_' + str(counter)
    #     setattr(this, name, PrimitiveStep(primitive=index.get_primitive('d3m.primitives.tods.timeseries_processing.' + primitive_map[timeseries_processing_list[x]] + '.' +  timeseries_processing_list[x])))
    #     this.name = PrimitiveStep(primitive=index.get_primitive('d3m.primitives.tods.timeseries_processing.' + primitive_map[timeseries_processing_list[x]] + '.' +  timeseries_processing_list[x]))

    #     this.name.add_argument(name='inputs', argument_type=ArgumentType.CONTAINER, data_reference='steps.' + str(counter - 1) + '.produce')
    #     for key, value in search_space.items():
    #       if timeseries_processing_list[x] in key:
    #         hp_name = key.replace(timeseries_processing_list[x] + '_', '')
    #         if value == "None":
    #           this.name.add_hyperparameter(name=hp_name, argument_type=ArgumentType.VALUE, data=None)
    #         elif value == "True":
    #           this.name.add_hyperparameter(name=hp_name, argument_type=ArgumentType.VALUE, data=True)
    #         elif value == "False":
    #           this.name.add_hyperparameter(name=hp_name, argument_type=ArgumentType.VALUE, data=False)
    #         else:
    #           this.name.add_hyperparameter(name=hp_name, argument_type=ArgumentType.VALUE, data=value)
    #     this.name.add_output('produce')
    #     pipeline_description.add_step(this.name)
    #     counter += 1


    # Step 2: extract_columns_by_semantic_types(attributes)
    step_3 = PrimitiveStep(primitive=index.get_primitive('d3m.primitives.tods.feature_analysis.' + search_space['feature_analysis']))
    step_3.add_argument(name='inputs', argument_type=ArgumentType.CONTAINER, data_reference='steps.2.produce')
    step_3.add_output('produce')
    step_3.add_hyperparameter(name='semantic_types', argument_type=ArgumentType.VALUE,
                    data=['https://metadata.datadrivendiscovery.org/types/Attribute'])
    pipeline_description.add_step(step_3)
    # counter += 1

    # Step 2: extract_columns_by_semantic_types(attributes)
    step_4 = PrimitiveStep(primitive=index.get_primitive('d3m.primitives.tods.detection_algorithm.' + search_space['detection_algorithm']))
    step_4.add_argument(name='inputs', argument_type=ArgumentType.CONTAINER, data_reference='steps.3.produce')
    step_4.add_output('produce')
    step_4.add_hyperparameter(name='semantic_types', argument_type=ArgumentType.VALUE,
                    data=['https://metadata.datadrivendiscovery.org/types/Attribute'])
    pipeline_description.add_step(step_4)

    step_5 = PrimitiveStep(primitive=index.get_primitive('d3m.primitives.tods.data_processing.construct_predictions'))
    step_5.add_argument(name='inputs', argument_type=ArgumentType.CONTAINER, data_reference='steps.4.produce')
    step_5.add_argument(name='reference', argument_type=ArgumentType.CONTAINER, data_reference='steps.1.produce')
    step_5.add_output('produce')
    pipeline_description.add_step(step_5)

    # feature_analysis_list = []

    # feature_analysis = search_space.pop('feature_analysis', None)
    # if ' ' in feature_analysis:
    #   feature_analysis_list = feature_analysis.split(' ')
    # else:
    #   feature_analysis_list.append(feature_analysis)


    # for x in range(len(feature_analysis_list)):
    #   this = sys.modules[__name__]
    #   name = 'step_' + str(counter)
    #   setattr(this, name, PrimitiveStep(primitive=index.get_primitive('d3m.primitives.tods.feature_analysis.' + feature_analysis_list[x])))
    #   this.name = PrimitiveStep(primitive=index.get_primitive('d3m.primitives.tods.feature_analysis.' + feature_analysis_list[x]))

    #   this.name.add_argument(name='inputs', argument_type=ArgumentType.CONTAINER, data_reference='steps.' + str(counter - 1) + '.produce')
    #   for key, value in search_space.items():
    #     if feature_analysis_list[x] in key:
    #       hp_name = key.replace(feature_analysis_list[x] + '_', '')
    #       if value == "None":
    #         this.name.add_hyperparameter(name=hp_name, argument_type=ArgumentType.VALUE, data=None)
    #       elif value == "True":
    #         this.name.add_hyperparameter(name=hp_name, argument_type=ArgumentType.VALUE, data=True)
    #       elif value == "False":
    #         this.name.add_hyperparameter(name=hp_name, argument_type=ArgumentType.VALUE, data=False)
    #       else:
    #         this.name.add_hyperparameter(name=hp_name, argument_type=ArgumentType.VALUE, data=value)
    #   this.name.add_output('produce')
    #   pipeline_description.add_step(this.name)
    #   counter += 1





    detection_algorithm_list = []

    detection_algorithm = search_space.pop('detection_algorithm', None)
    if ' ' in detection_algorithm:
      detection_algorithm_list = detection_algorithm.split(' ')
    else:
      detection_algorithm_list.append(detection_algorithm)

    for x in range(len(detection_algorithm_list)):
      this = sys.modules[__name__]
      name = 'step_' + str(counter) 
      setattr(this, name, PrimitiveStep(primitive=index.get_primitive('d3m.primitives.tods.detection_algorithm.' + detection_algorithm_list[x])))
      this.name = PrimitiveStep(primitive=index.get_primitive('d3m.primitives.tods.detection_algorithm.' + detection_algorithm_list[x]))

      this.name.add_argument(name='inputs', argument_type=ArgumentType.CONTAINER, data_reference='steps.' + str(counter - 1) + '.produce')
      for key, value in search_space.items():
        if detection_algorithm_list[x] in key:
          hp_name = key.replace(detection_algorithm_list[x] + '_', '')
          if value == "None":
            this.name.add_hyperparameter(name=hp_name, argument_type=ArgumentType.VALUE, data=None)
          elif value == "True":
            this.name.add_hyperparameter(name=hp_name, argument_type=ArgumentType.VALUE, data=True)
          elif value == "False":
            this.name.add_hyperparameter(name=hp_name, argument_type=ArgumentType.VALUE, data=False)
          else:
            this.name.add_hyperparameter(name=hp_name, argument_type=ArgumentType.VALUE, data=value)
      this.name.add_output('produce')
      pipeline_description.add_step(this.name)
      counter += 1







    for i in range(1):
      this = sys.modules[__name__]
      name = 'step_' + str(counter)
      setattr(this, name, PrimitiveStep(primitive=index.get_primitive('d3m.primitives.tods.data_processing.construct_predictions')))
      this.name = PrimitiveStep(primitive=index.get_primitive('d3m.primitives.tods.data_processing.construct_predictions'))

      this.name.add_argument(name='inputs', argument_type=ArgumentType.CONTAINER, data_reference='steps.' + str(counter - 1) + '.produce')
      this.name.add_argument(name='reference', argument_type=ArgumentType.CONTAINER, data_reference='steps.1.produce')
      this.name.add_output('produce')
      pipeline_description.add_step(this.name)
      counter += 1




    pipeline_description.add_output(name='output predictions', data_reference='steps.' + str(counter - 1) + '.produce')
    data = pipeline_description.to_json()
    # print(data)
    return pipeline_description

  def clearer_best_config(self, best_config):
    print('the best choice for timeseries_processing is: ', best_config['timeseries_processing'])
    for key, value in best_config.items():
      temp = best_config['timeseries_processing'].split(" ")
      for i in temp:
        if (i + '_') in key:
          print("the best" + key.replace(i + '_', " ") + " for " + 
          i + ": " + str(value))

    print('the best choice for feature analysis is: ', best_config['feature_analysis'])
    for key, value in best_config.items():
      temp = best_config['feature_analysis'].split(" ")
      for i in temp:
        if (i + '_') in key:
          print("the best" + key.replace(i + '_', " ") + " for " + 
          i + ": " + str(value))

    print('the best choice for detection algorithm is: ', best_config['detection_algorithm'])
    for key, value in best_config.items():
      temp = best_config['detection_algorithm'].split(" ")
      for i in temp:
        if (i + '_') in key:
          print("the best" + key.replace(i + '_', " ") + " for " + 
          i + ": " + str(value))

  def find_best_pipeline_id(self, best_config, df):
    for key, value in best_config.items():
        df = df.loc[df['config/' + str(key)] == value]

    return ray.get(self.stats.get_fitted_pipeline_list.remote())[df.index[0]]



def datapath_to_dataset(path, target_index):
  df = pd.read_csv(path)
  return generate_dataset(df, target_index)

def json_to_searchspace(path, config, use_all_combination, ignore_hyperparams):
  import json

  with open(path) as f:
    data = json.load(f)
  
  def get_all_comb(stuff):
    import itertools
    temp = []
    for L in range(0, len(stuff)+1):
      for subset in itertools.permutations(stuff, L):
        subset = list(subset)
        temp2 = ''
        for i in subset:
          temp2 = temp2 + (i + ' ')
        temp2 = temp2[:-1]
        if temp2 != '':
          temp.append(temp2)
    return temp

  search_space = {}
  from itertools import permutations
  for primitive_type, primitive_list in data.items():
    temp = []
    if not ignore_hyperparams:
      for primitive_name, hyperparams in primitive_list.items():
        temp.append(primitive_name)
        for hyperparams_name, hyperparams_value in hyperparams.items():
          name = primitive_name + '_' + hyperparams_name
          if config['searching_algorithm'] == 'hyperopt':
            search_space[name] = tune.choice(hyperparams_value)
          else:
            search_space[name] = tune.grid_search(hyperparams_value)
    if use_all_combination == True:
      if config['searching_algorithm'] == 'hyperopt':
        search_space[primitive_type] = tune.choice(get_all_comb(temp))
      else:
        search_space[primitive_type] = tune.grid_search(get_all_comb(temp))
    elif use_all_combination == False:
      if config['searching_algorithm'] == 'hyperopt':
        search_space[primitive_type] = tune.choice(temp)
      else:
        search_space[primitive_type] = tune.grid_search(temp)

  return search_space