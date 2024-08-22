import streamlit as st
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.impute import SimpleImputer
from io import BytesIO

def calculate_sales_velocity(sales_data):
    if 'day' not in sales_data.columns:
        st.error("The 'day' column is missing from the sales data. Please ensure the correct file is uploaded.")
        return None

    sales_data['day'] = pd.to_datetime(sales_data['day'])
    sales_velocity = sales_data.groupby('variant_sku')['ordered_item_quantity'].sum() / \
                     (sales_data['day'].max() - sales_data['day'].min()).days
    return sales_velocity

def generate_forecast(sales_data, sales_velocity):
    forecast_30 = {}
    forecast_90 = {}
    for sku in sales_velocity.index:
        sku_data = sales_data[sales_data['variant_sku'] == sku]
        if len(sku_data) >= 2:  # At least two data points needed for Linear Regression
            model = LinearRegression()
            X = np.arange(len(sku_data)).reshape(-1, 1)
            y = sku_data['ordered_item_quantity'].values
            model.fit(X, y)
            future_sales = model.predict(np.array([[len(sku_data) + i] for i in range(90)]))
            forecast_30[sku] = future_sales[:30].sum()  # 30-day forecast
            forecast_90[sku] = future_sales.sum()  # 90-day forecast
        else:
            forecast_30[sku] = sales_velocity[sku] * 30
            forecast_90[sku] = sales_velocity[sku] * 90
    return forecast_30, forecast_90

def impute_lead_time(inventory_data):
    imputer = SimpleImputer(strategy='mean')
    inventory_data['Lead time'] = imputer.fit_transform(inventory_data[['Lead time']])
    return inventory_data

def generate_report(sales_data, inventory_data):
    sales_velocity = calculate_sales_velocity(sales_data)
    if sales_velocity is None:
        return None, None

    forecast_30, forecast_90 = generate_forecast(sales_data, sales_velocity)
    inventory_data = impute_lead_time(inventory_data)

    forecast_report = []
    reorder_report = []

    for sku in inventory_data['Part No.']:
        product_name = inventory_data.loc[inventory_data['Part No.'] == sku, 'Part description'].values[0]
        velocity = sales_velocity.get(sku, 0)
        forecast_30_qty = forecast_30.get(sku, 0)
        forecast_90_qty = forecast_90.get(sku, 0)
        inventory_need_30 = forecast_30_qty  # Simple calculation for demo purposes

        inbound_qty = inventory_data.loc[inventory_data['Part No.'] == sku, 'Expected, available'].values[0]
        reorder_qty = max(forecast_30_qty + forecast_90_qty - (inventory_data.loc[inventory_data['Part No.'] == sku, 'In stock'].values[0] + inbound_qty), 0)

        forecast_report.append([product_name, sku, velocity, forecast_30_qty, forecast_90_qty, inventory_need_30])
        reorder_report.append([product_name, sku, inbound_qty, reorder_qty])

    forecast_df = pd.DataFrame(forecast_report, columns=['Product', 'SKU', 'Sales Velocity', 'Forecast Sales Qty (30 Days)', 'Forecast Sales Qty (90 Days)', 'Forecast Inventory Need (30 Days)'])
    reorder_df = pd.DataFrame(reorder_report, columns=['Product', 'SKU', 'Inbound', 'Qty to Reorder Now'])

    return forecast_df, reorder_df

def to_excel(forecast_df, reorder_df):
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    forecast_df.to_excel(writer, index=False, sheet_name='Forecast')
    reorder_df.to_excel(writer, index=False, sheet_name='Reorder')
    writer.save()
    processed_data = output.getvalue()
    return processed_data

# Streamlit app
st.title("Reorder Report Generator")

st.sidebar.header("Upload Data")
sales_file = st.sidebar.file_uploader("Upload Sales Data (CSV)", type="csv")
inventory_file = st.sidebar.file_uploader("Upload Inventory Data (CSV)", type="csv")

if sales_file and inventory_file:
    sales_data = pd.read_csv(sales_file)
    inventory_data = pd.read_csv(inventory_file)
    
    if st.sidebar.button("Generate Reorder Report"):
        forecast_df, reorder_df = generate_report(sales_data, inventory_data)
        
        if forecast_df is not None and reorder_df is not None:
            st.subheader("Forecast Report")
            st.dataframe(forecast_df)
            
            st.subheader("Reorder Report")
            st.dataframe(reorder_df)
            
            excel_data = to_excel(forecast_df, reorder_df)
            st.download_button(
                label="Download Report as Excel",
                data=excel_data,
                file_name='Reorder_Report.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
else:
    st.sidebar.warning("Please upload both Sales and Inventory CSV files to proceed.")
