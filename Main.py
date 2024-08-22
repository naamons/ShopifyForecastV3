import streamlit as st
import pandas as pd
import numpy as np
from sklearn.impute import SimpleImputer
from io import BytesIO

def calculate_sales_velocity(sales_data, window=7):
    if 'day' not in sales_data.columns:
        st.error("The 'day' column is missing from the sales data. Please ensure the correct file is uploaded.")
        return None

    sales_data['day'] = pd.to_datetime(sales_data['day'])
    sales_data = sales_data.sort_values(by='day')
    
    # Calculate rolling average to smooth out sales data
    sales_data['rolling_quantity'] = sales_data.groupby('variant_sku')['ordered_item_quantity'].transform(lambda x: x.rolling(window, min_periods=1).mean())
    
    if 'rolling_quantity' not in sales_data.columns:
        st.error("'rolling_quantity' column could not be created. Check the data processing steps.")
        return None

    sales_velocity = sales_data.groupby('variant_sku')['rolling_quantity'].sum() / \
                     (sales_data['day'].max() - sales_data['day'].min()).days
    return sales_velocity

def generate_forecast(sales_data, sales_velocity):
    forecast_30 = {}
    forecast_90 = {}
    for sku in sales_velocity.index:
        sku_data = sales_data[sales_data['variant_sku'] == sku]
        if 'rolling_quantity' in sku_data.columns:
            rolling_quantity = sku_data['rolling_quantity'].values
            if len(rolling_quantity) >= 2:  # At least two data points needed for a meaningful forecast
                forecast_30[sku] = rolling_quantity[-30:].sum()
                forecast_90[sku] = rolling_quantity[-90:].sum()
            else:
                forecast_30[sku] = sales_velocity[sku] * 30
                forecast_90[sku] = sales_velocity[sku] * 90
        else:
            st.error(f"'rolling_quantity' column missing in data for SKU {sku}")
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
        
        if reorder_qty > 0:  # Only include items that need to be reordered
            reorder_report.append([product_name, sku, inbound_qty, reorder_qty, forecast_30_qty])

    forecast_df = pd.DataFrame(forecast_report, columns=['Product', 'SKU', 'Sales Velocity', 'Forecast Sales Qty (30 Days)', 'Forecast Sales Qty (90 Days)', 'Forecast Inventory Need (30 Days)'])
    reorder_df = pd.DataFrame(reorder_report, columns=['Product', 'SKU', 'Inbound', 'Qty to Reorder Now', 'Forecast Sales Qty (30 Days)'])

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
