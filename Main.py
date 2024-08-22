import streamlit as st
import pandas as pd
import numpy as np
from sklearn.impute import SimpleImputer
from io import BytesIO

def calculate_sales_velocity_90days(sales_data):
    sales_data['Total Quantity'] = sales_data['net_quantity']
    sales_velocity = sales_data.groupby('product_title')['Total Quantity'].sum() / 90  # Average daily sales over 90 days
    return sales_velocity

def generate_forecast(sales_velocity, days=30):
    return sales_velocity * days  # Forecasting based on current velocity

def generate_report(sales_data, inventory_data):
    sales_velocity = calculate_sales_velocity_90days(sales_data)
    forecast_30 = generate_forecast(sales_velocity, 30)

    # Impute lead time: Assume 30 days where lead time is missing
    inventory_data['Lead time'] = inventory_data['Lead time'].fillna(30)

    forecast_report = []
    reorder_report = []

    for sku in inventory_data['Part No.']:
        product_name = inventory_data.loc[inventory_data['Part No.'] == sku, 'Part description'].values[0]
        velocity = sales_velocity.get(product_name, 0)
        forecast_30_qty = forecast_30.get(product_name, 0)
        current_stock = inventory_data.loc[inventory_data['Part No.'] == sku, 'In stock'].values[0]
        inbound_qty = inventory_data.loc[inventory_data['Part No.'] == sku, 'Expected, available'].values[0]
        lead_time = inventory_data.loc[inventory_data['Part No.'] == sku, 'Lead time'].values[0]

        # Forecasted inventory need including lead time
        forecast_need_lead_time = velocity * lead_time
        
        # Reorder quantity calculation
        reorder_qty = max(forecast_30_qty + forecast_need_lead_time - (current_stock + inbound_qty), 0)

        forecast_report.append([product_name, sku, velocity, forecast_30_qty, current_stock, inbound_qty, lead_time, forecast_need_lead_time])
        
        if reorder_qty > 0:
            reorder_report.append([product_name, sku, current_stock, inbound_qty, lead_time, reorder_qty, forecast_30_qty])

    forecast_df = pd.DataFrame(forecast_report, columns=[
        'Product', 'SKU', 'Sales Velocity', 'Forecast Sales Qty (30 Days)', 'Current Stock', 
        'Inbound Stock', 'Lead Time (Days)', 'Forecast Inventory Need (With Lead Time)'
    ])
    
    reorder_df = pd.DataFrame(reorder_report, columns=[
        'Product', 'SKU', 'Current Stock', 'Inbound Stock', 'Lead Time (Days)', 
        'Qty to Reorder Now', 'Forecast Sales Qty (30 Days)'
    ])

    # Format reorder quantities as whole numbers
    reorder_df['Qty to Reorder Now'] = reorder_df['Qty to Reorder Now'].astype(int)
    reorder_df['Forecast Sales Qty (30 Days)'] = reorder_df['Forecast Sales Qty (30 Days)'].astype(int)

    return forecast_df, reorder_df

def to_excel(forecast_df, reorder_df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        forecast_df.to_excel(writer, index=False, sheet_name='Forecast')
        reorder_df.to_excel(writer, index=False, sheet_name='Reorder')
    processed_data = output.getvalue()
    return processed_data

# Streamlit app
st.title("Reorder Report Generator (90 Days Sales)")

st.sidebar.header("Upload Data")
sales_file = st.sidebar.file_uploader("Upload 90-Day Sales Data (CSV)", type="csv")
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
    st.sidebar.warning("Please upload both 90-Day Sales and Inventory CSV files to proceed.")
