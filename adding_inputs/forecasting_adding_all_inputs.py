import glob
import numpy as np
import pandas as pd
import gpflow
import random
from sklearn.metrics import mean_squared_error
import pickle
import argparse
import os

"""#### CPU cores """
os.environ["OMP_NUM_THREADS"] = "8"

import tensorflow as tf

tf.config.threading.set_inter_op_parallelism_threads(1)
tf.config.threading.set_intra_op_parallelism_threads(1)

nov_df = pd.read_csv('nov-data.csv')
weather_df = pd.read_csv('weather-data.csv')

nov_df_no_outliers = pd.DataFrame()

for site in nov_df.site_id.unique():
  site_df = nov_df[nov_df['site_id']==site]
  Q1 = site_df['pm2_5_calibrated_value'].quantile(0.25)
  Q3 = site_df['pm2_5_calibrated_value'].quantile(0.75)
  IQR = Q3 - Q1
  final_df = site_df[~((site_df['pm2_5_calibrated_value']<(Q1-1.5*IQR)) | (site_df['pm2_5_calibrated_value']>(Q3+1.5*IQR)))]
  nov_df_no_outliers = pd.concat([nov_df_no_outliers, final_df], ignore_index=True)

df = nov_df_no_outliers

sites = df.site_id.unique()
print("Number of sites:")
print(sites.shape)

print("Shape of data frame:")
print(df.shape)

def add_times_to_df(df):
    strtime_to_idx = {f"{idx:02d}:00": idx for idx in range(24)}
    days_and_times = np.array([v.split(" ") for v in df.timestamp.values])

    if 'Day' not in df:
        df.insert(0, 'Day', days_and_times[:, 0])
    if 'Time' not in df:
        df.insert(1, 'Time', [time[:-3] for time in days_and_times[:, 1]])
    if 'IndexTime' not in df:
        df.insert(2, 'IndexTime', [strtime_to_idx[time] for time in df.Time.values])
    if 'IndexDay' not in df:
        df['Day'] = pd.to_datetime(df['Day'])
        df.insert(3, 'IndexDay', df['Day'].dt.weekday)

add_times_to_df(df)
# df = df[['Day', 'Time', 'IndexTime', 'IndexDay', 'timestamp',
# 'pm2_5_calibrated_value', 'pm2_5_raw_value', 'latitude', 'longitude', 'site_id',
# 'wind_speed', 'wind_gusts', 'wind_direction', 'temperature', 'precipitation',
# 'humidity']]
df = df[['Day', 'Time', 'IndexTime', 'IndexDay', 'timestamp',
'pm2_5_calibrated_value', 'pm2_5_raw_value', 'latitude', 'longitude', 'site_id']]

df['timestamp'] = pd.to_datetime(df['timestamp'])
weather_df['datetime'] = pd.to_datetime(weather_df['datetime'], utc=True)

df = df.merge(weather_df, left_on='timestamp', right_on='datetime')
df = df.drop(['windgust', 'datetime'], axis=1)

max_calibrated_pm2_5 = df['pm2_5_calibrated_value'].max(axis=0)
min_calibrated_pm2_5 = df['pm2_5_calibrated_value'].min(axis=0)
max_raw_pm2_5 = df['pm2_5_raw_value'].max(axis=0)
min_raw_pm2_5 = df['pm2_5_raw_value'].min(axis=0)
max_latitude = df['latitude'].max(axis=0)
min_latitude = df['latitude'].min(axis=0)
max_longitude = df['longitude'].max(axis=0)
min_longitude = df['longitude'].min(axis=0)

mean_calibrated_pm2_5 = df['pm2_5_calibrated_value'].mean(axis=0)
std_calibrated_pm2_5 = df['pm2_5_calibrated_value'].std(axis=0)
mean_raw_pm2_5 = df['pm2_5_raw_value'].mean(axis=0)
std_raw_pm2_5 = df['pm2_5_raw_value'].std(axis=0)
mean_latitude = df['latitude'].mean(axis=0)
std_latitude = df['latitude'].std(axis=0)
mean_longitude = df['longitude'].mean(axis=0)
std_longitude = df['longitude'].std(axis=0)

# mean_wind_speed = df['wind_speed'].mean(axis=0)
# std_wind_speed = df['wind_speed'].std(axis=0)
# mean_wind_direction = df['wind_direction'].mean(axis=0)
# std_wind_direction = df['wind_direction'].std(axis=0)
# mean_wind_gusts = df['wind_gusts'].mean(axis=0)
# std_wind_gusts = df['wind_gusts'].std(axis=0)
# mean_temperature = df['temperature'].mean(axis=0)
# std_temperature = df['temperature'].std(axis=0)
# mean_precipitation = df['precipitation'].mean(axis=0)
# std_precipitation = df['precipitation'].std(axis=0)
# mean_humidity = df['humidity'].mean(axis=0)
# std_humidity = df['humidity'].std(axis=0)
mean_wind_speed = df['windspeed'].mean(axis=0)
std_wind_speed = df['windspeed'].std(axis=0)
mean_wind_direction = df['winddir'].mean(axis=0)
std_wind_direction = df['winddir'].std(axis=0)
mean_temperature = df['temp'].mean(axis=0)
std_temperature = df['temp'].std(axis=0)
mean_precipitation = df['precip'].mean(axis=0)
std_precipitation = df['precip'].std(axis=0)
mean_humidity = df['humidity'].mean(axis=0)
std_humidity = df['humidity'].std(axis=0)
mean_cloud_cover = df['cloudcover'].mean(axis=0)
std_cloud_cover = df['cloudcover'].std(axis=0)

last_day = df[df['Day'].astype(str)=='2021-11-30']
print(last_day.site_id.unique().shape)

last_hour = last_day[last_day['IndexTime']==23]
print(last_hour.site_id.unique().shape)


# #### Forecasting last hour

train = df.drop(last_hour.index)


def train_test_forecast_hour_gp(df, site_id, kernel, input_features):
    test = df.loc[last_day.index]
    test = test[test['site_id'] == site_id]

    mses = np.zeros(3)

    for i in range(3):
        if len(test) == 0:
            return 0
        if len(test) > 250:
            rand_test = test.sample(n=250, random_state=i)
        else:
            rand_test = test

        if len(train) > 1000:
            rand_train = train.sample(n=1000, random_state=i)
        else:
            rand_train = train

        # X = rand_train[['IndexDay', 'IndexTime', 'latitude', 'longitude',
        # 'wind_speed', 'wind_gusts', 'wind_direction', 'temperature', 'precipitation',
        # 'humidity']].astype('float').to_numpy()
        X = rand_train[['IndexDay', 'IndexTime', 'latitude', 'longitude',
        'windspeed', 'cloudcover', 'winddir', 'temp', 'precip', 'humidity']].astype('float').to_numpy()

        Y = rand_train[['pm2_5_calibrated_value']].to_numpy()
        X_normalised = X.copy().T
        X_normalised[0] /= 7
        X_normalised[1] /= 24
        X_normalised[2] = (X_normalised[2] - mean_latitude) / std_latitude
        X_normalised[3] = (X_normalised[3] - mean_longitude) / std_longitude
        X_normalised[4] = (X_normalised[4] - mean_wind_speed) / std_wind_speed
        X_normalised[5] = (X_normalised[5] - mean_cloud_cover) / std_cloud_cover
        X_normalised[6] = (X_normalised[6] - mean_wind_direction) / std_wind_direction
        X_normalised[7] = (X_normalised[7] - mean_temperature) / std_temperature
        X_normalised[8] = (X_normalised[8] - mean_precipitation) / std_precipitation
        X_normalised[9] = (X_normalised[9] - mean_humidity) / std_humidity

        X_normalised = X_normalised.T

        X_normalised = X_normalised[:, input_features]

        Y_normalised = (Y - mean_calibrated_pm2_5) / std_calibrated_pm2_5

        model = gpflow.models.GPR(
          (X_normalised, Y_normalised),
          kernel=kernel
        )

        opt = gpflow.optimizers.Scipy()
        opt.minimize(model.training_loss, model.trainable_variables)

        # testX = test[['IndexDay', 'IndexTime', 'latitude', 'longitude',
        # 'wind_speed', 'wind_gusts', 'wind_direction', 'temperature', 'precipitation',
        # 'humidity']].astype('float').to_numpy()
        testX = test[['IndexDay', 'IndexTime', 'latitude', 'longitude',
        'windspeed', 'cloudcover', 'winddir', 'temp', 'precip', 'humidity']].astype('float').to_numpy()

        testY = test[['pm2_5_calibrated_value']].to_numpy()

        testX_normalised = testX.copy().T
        testX_normalised[0] /= 7
        testX_normalised[1] /= 24
        testX_normalised[2] = (testX_normalised[2] - mean_latitude) / std_latitude
        testX_normalised[3] = (testX_normalised[3] - mean_longitude) / std_longitude
        testX_normalised[4] = (testX_normalised[4] - mean_wind_speed) / std_wind_speed
        testX_normalised[5] = (testX_normalised[5] - mean_cloud_cover) / std_cloud_cover
        testX_normalised[6] = (testX_normalised[6] - mean_wind_direction) / std_wind_direction
        testX_normalised[7] = (testX_normalised[7] - mean_temperature) / std_temperature
        testX_normalised[8] = (testX_normalised[8] - mean_precipitation) / std_precipitation
        testX_normalised[9] = (testX_normalised[9] - mean_humidity) / std_humidity

        testX_normalised = testX_normalised.T

        testX_normalised = testX_normalised[:, input_features]

        y_mean, y_var = model.predict_y(testX_normalised)
        y_mean_unnormalised = (y_mean * (std_calibrated_pm2_5)) + mean_calibrated_pm2_5

        mse = mean_squared_error(y_mean_unnormalised, testY)
        mses[i] = mse
    return np.average(mses)

day_period = gpflow.kernels.Periodic(gpflow.kernels.SquaredExponential(active_dims=[0], lengthscales=[0.14]), period=7)
hour_period = gpflow.kernels.Periodic(gpflow.kernels.SquaredExponential(active_dims=[1], lengthscales=[0.04]), period=24)

rbf1 = gpflow.kernels.SquaredExponential(active_dims=[2], lengthscales=[0.2])
rbf2 = gpflow.kernels.SquaredExponential(active_dims=[3], lengthscales=[0.2])
rbf3 = gpflow.kernels.SquaredExponential(active_dims=[4, 5, 6, 7, 8, 9])

# periodic_kernel = day_period + hour_period + (rbf1 * rbf2) + rbf3
periodic_kernel = day_period + hour_period + (rbf1 * rbf2) + rbf3
gpflow.set_trainable(periodic_kernel.kernels[0].period, False)
gpflow.set_trainable(periodic_kernel.kernels[1].period, False)

input_features = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]

forecast_hour_mses = np.zeros(len(sites))

for i in range(0, len(sites)):
    mse = train_test_forecast_hour_gp(df, sites[i], periodic_kernel, input_features)
    forecast_hour_mses[i] = mse

fm_hour = forecast_hour_mses[forecast_hour_mses != 0]

avg_rmse = np.sqrt(np.average(fm_hour))
max_rmse = np.sqrt(np.max(fm_hour))
min_rmse = np.sqrt(np.min(fm_hour))
print(min_rmse)
print(avg_rmse)
print(max_rmse)

site_rmses = dict(zip(sites, np.sqrt(fm_hour)))

output_folder = 'forecastingAddingAllInputs'

os.makedirs(output_folder, exist_ok = True)

np.savetxt(output_folder + '/rmses_all.txt', np.array([min_rmse, avg_rmse, max_rmse]))

import csv
with open(output_folder + '/site_rmses_all.csv', 'w') as fp:
    writer = csv.writer(fp)
    writer.writerows(site_rmses.items())