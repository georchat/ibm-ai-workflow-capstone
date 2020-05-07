#!/usr/bin/env python

import os
import re
import time
import numpy as np
import pandas as pd
from datetime import datetime
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.pipeline import Pipeline

## import function to load feature matrix
from data_ingestion import load_feature_matrix

class FeatureEngineer(BaseEstimator, TransformerMixin):
    """
    apply rolling window to engineer features
    """
    def __init__(self, shift=1, attributes=['revenue'], func="sum"):
        self.shift = shift
        self.attributes = attributes
        self.freq = "{}D".format(self.shift)
        self.func = func
    
    def fit(self, X, y=None):
        return self
    
    def transform(self, X, y=None):
        
        ## set time as index
        X_ts = X.set_index(["invoice_date"])
        
        ## rolling window
        if self.func == "sum":
            X_eng = X_ts[self.attributes].rolling(self.freq, closed="left").sum()
        else:
            X_eng = X_ts[self.attributes].rolling(self.freq, closed="left").mean()
        
        ## merge with initial dataset and fill NAs
        X_eng = X_ts.merge(X_eng, left_index=True, right_index=True, how="left", suffixes=["","_m{}".format(self.freq)]).fillna(0)
        return X_eng.reset_index()

class TargetEngineer(BaseEstimator, TransformerMixin):
    """
    apply day rolling window and shift backwards
    to engineer the predicted summed revenue
    """
    def __init__(self, shift=30, attributes=['revenue']):
        self.shift = shift
        self.attributes = attributes
        self.freq = "{}D".format(self.shift)
    
    def fit(self, X, y=None):
        return self
    
    def transform(self, X, y=None):
        
        ## set time as index
        X_ts = X.set_index(["invoice_date"])
        
        ## rolling window
        X_eng = X_ts[self.attributes].rolling(self.freq, closed="left").sum().shift(-self.shift,"D")
        
        ## merge with the original
        X_eng = X_ts.merge(X_eng, left_index=True, right_index=True, how="left", suffixes=["","_p{}".format(self.freq)])
        
        return X_eng.reset_index()

def engineer_features(training=True, clean=False):
    """
    engineer feature matrix and target value
    """
    
    ## load feature matrix
    fm = load_feature_matrix(training=training, clean=clean)
    
    print("...engineering features and target value")
    
    ## ensure that all days are accounted for each country
    fm = fm.set_index(["invoice_date","country"]).unstack(1).asfreq("1D")
   
    ## fill NAs with zero (assume no revenue was generated that day)
    fm = fm.fillna(0).stack(1).reset_index()
    
    ## unique countries
    countries = fm.country.unique()
    
    ## original features
    features = ["invoice_date","purchases","unique_invoices","unique_streams","total_views","revenue"]
    
    ## non revenue feautures
    nonrevenue_features = ["purchases","unique_invoices","unique_streams","total_views"]
    
    eng_features = {}
    for country in countries:
        
        ## filter on country
        df = fm.query("country==@country").drop("country", axis=1)
        
        ## build pipeline to transform features
        pipe_engineer = Pipeline([
            ("revenue7d", FeatureEngineer(shift=7)),
            ("revenue14D", FeatureEngineer(shift=14)),
            ("revenue28D", FeatureEngineer(shift=28)),
            ("revenue35D", FeatureEngineer(shift=35)),
            ("revenue54D", FeatureEngineer(shift=54)),
            ("nonrevenue30D", FeatureEngineer(attributes=nonrevenue_features, shift=30, func="mean"))
        ])
        
        ## engineer features
        X = pipe_engineer.transform(df)
        
        ## features quality ckeck
        date = '2018-02-01'
        v1 = df.query("invoice_date<@date")[["revenue"]].tail(14).sum().values
        v2 = X.query("invoice_date==@date")["revenue_m14D"].values.ravel()
        if not np.array_equal(v1.round(2), v2.round(2)):
            print("Opps! Engineer features didn't work as expected")
            
        ## drop original features
        X.drop(features, axis=1, inplace=True)
        
        ## build instance to transform target
        target_eng = TargetEngineer()
        
        ## engineer target
        y = target_eng.transform(df)
        
        ## target quality check
        date = '2018-02-01'
        v1 = df.query("invoice_date>=@date")[["revenue"]].head(30).sum().values
        v2 = y.query("invoice_date>=@date").head(1)["revenue_p30D"].values.ravel()
        if not np.array_equal(v1.round(2), v2.round(2)):
            print("Opps! Engineer target didn't work as expected")
            
        y.drop(features, axis=1, inplace=True)
            
        if training:
            ## remove dates with NAs
            ## the 30-day rolling and shift back for the target results in NAs for the last 30 days
            mask = y["revenue_p30D"].notna()
            X = X[mask]
            y = y[mask]
            X.reset_index(drop=True, inplace=True)
            y.reset_index(drop=True, inplace=True)
        
        features_labels = X.columns.values
        
        ## store them as numpy arrays
        eng_features[country]= (X.values, y.values.ravel(), features_labels)
    
    return eng_features

if __name__ == "__main__":
    
    run_start = time.time()
    print("...transforming data")
  
    ## engineer data
    model_datasets = engineer_features()
    
    for key, item in model_datasets.items():
        print(key, item[0].shape, item[1].shape)
    
    ## metadata
    m, s = divmod(time.time()-run_start,60)
    h, m = divmod(m, 60)
    print("load time:", "%d:%02d:%02d"%(h, m, s))
    
    print("...done")
    