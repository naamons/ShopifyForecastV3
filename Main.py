import streamlit as st
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.impute import SimpleImputer

def calculate_sales_velocity(sales_data):
    # Use 'day' instead of 'Date'
    if 'day' not in sales_data.columns:
        st.error("The 'day' column is missing from the sales data. Please ensure the correct file is uploaded.")
        return None

    sales_data['day'] = pd.to_datetime(sales_data['day'])
    sales_velocity = sales_data.groupby('variant_sku')['ordered_item_quantity'].sum() / \
                     (sales_data['day'].max() - sales_data['day'].min()).days
    return sales_velocity

def generate_forecast(sales_data, sales_velocity):
    forecast = {}
    for sku in sales_velocity.index:
        sku_data = sales_data[sales_data['variant_sku'] == sku]
        if len(sku_data) >= 2:  # At least two data points needed for Linear Regression
            model = LinearRegression()
            X = np.arange(len(sku_data)).reshape(-1, 1)
            y = sku_data['ordered_item_quantity'].values
            model.fit(X, y)
            future_sales = model.predict(np.array([[len(sku_data) + i] for i in range(30)]))
            forecast[sku] = future_sales.sum() / 30  # 30-day average forecast
        else:
            forecast[sku] = sales_velocity[sku]  # Use sales velocity if insufficient data
    return forecast

def impute_lead_time(inventory_data):
    imputer = SimpleImputer(strategy='mean')
    inventory_data['Lead time'] = imputer.fit_transform(inventory_data[['Lead time']])
    return inventory_data

def generate_reorder_report(sales_data, inventory_data):
    # Calculate sales velocity
    sales_velocity = calculate_sales_velocity(sales_data)
    if sales_velocity is None:
        return None

    # Generate sales forecast
    forecast = generate_forecast(sales_data, sales_velocity)

    # Impute lead time for null values
    inventory_data = impute_lead_time(inventory_data)

    # Merge data
    inventory_data.set_index('Part No.', inplace=True)
    reorder_data = inventory_data.copy()
    reorder_data['Sales Velocity'] = reorder_data.index.map(sales_velocity)
    reorder_data['Forecast Demand'] = reorder_data.index.map(forecast)

    # Calculate reorder quantity
    reorder_data['Reorder Quantity'] = (reorder_data['Forecast Demand'] * reorder_data['Lead time']) \
                                        - (reorder_data['In stock'] + reorder_data['Expected, available'])
    reorder_data['Reorder Quantity'] = reorder_data['Reorder Quantity'].apply(lambda x: max(x, 0))

    return reorder_data[['Reorder Quantity', 'Sales Velocity', 'Forecast Demand', 'Lead time']]

# Streamlit app
st.title("Reorder Report Generator")

st.sidebar.header("Upload Data")
sales_file = st.sidebar.file_uploader("Upload Sales Data (CSV)", type="csv")
inventory_file = st.sidebar.file_uploader("Upload Inventory Data (CSV)", type="csv")

if sales_file and inventory_file:
    sales_data = pd.read_csv(sales_file)
    inventory_data = pd.read_csv(inventory_file)
    
    if st.sidebar.button("Generate Reorder Report"):
        reorder_report = generate_reorder_report(sales_data, inventory_data)
        
        if reorder_report is not None:
            st.subheader("Reorder Report")
            st.dataframe(reorder_report)
            
            csv = reorder_report.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="Download Reorder Report as CSV",
                data=csv,
                file_name='Reorder_Report.csv',
                mime='text/csv',
            )
else:
    st.sidebar.warning("Please upload both Sales and Inventory CSV files to proceed.")
