from sklearn import linear_model
from sklearn.preprocessing import PolynomialFeatures


# prepare for the dataset
input_data = [
  [6, 1],
  [7, 1]
]

output_data = [
  2,
  5
]

# select a machine learning model (algorithm)
## linear regression
model = linear_model.LinearRegression()
## polynomial regression
poly = PolynomialFeatures(degree=2)
input_data_poly = poly.fit_transform(input_data)
model2 = linear_model.LinearRegression()

# train the model (learn)
model.fit(input_data, output_data)
model2.fit(input_data_poly, output_data)

# print("Slope (m):", model.coef_[0])
# print("Intercept (b):", model.intercept_)

# use the model to make predictions
res = model.predict([ [9.5, 1], [10.5, 1], [11.5, 1], [14, 1] ])
print(res)
res = model2.predict(poly.fit_transform([ [9.5, 1], [10.5, 1], [11.5, 1], [14, 1] ]))
print(res)

res = model2.predict(poly.fit_transform([ [9.5, 6], [10.5, 6], [11.5, 6], [14, 6] ]))
print(res)