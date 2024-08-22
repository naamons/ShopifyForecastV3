import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
import matplotlib.pyplot as plt

def calculate_sales_velocity_90days(sales_data):
    sales_data['Total Quantity'] = sales_data['net_quantity']
    sales_velocity = sales_data.groupby('variant_sku')['Total Quantity'].sum() / 90  # Average daily sales over 90 days
    return sales_velocity

def generate_forecast(sales_velocity, days=30):
    return sales_velocity * days  # Forecasting based on current velocity

def generate_report(sales_data, inventory_data, safety_stock_days):
    sales_velocity = calculate_sales_velocity_90days(sales_data)
    forecast_30 = generate_forecast(sales_velocity, 30)

    # Impute lead time: Assume 30 days where lead time is missing
    inventory_data['Lead time'] = inventory_data['Lead time'].fillna(30)

    forecast_report = []
    reorder_report = []

    for sku in inventory_data['Part No.']:
        product_name = inventory_data.loc[inventory_data['Part No.'] == sku, 'Part description'].values[0]
        velocity = sales_velocity.get(sku, 0)
        if velocity <= 0:
            continue  # Skip SKUs with no sales activity
        
        forecast_30_qty = round(forecast_30.get(sku, 0))
        current_available = inventory_data.loc[inventory_data['Part No.'] == sku, 'Available'].values[0]
        inbound_qty = inventory_data.loc[inventory_data['Part No.'] == sku, 'Expected, available'].values[0]
        lead_time = inventory_data.loc[inventory_data['Part No.'] == sku, 'Lead time'].values[0]

        # Forecasted inventory need including lead time and safety stock
        forecast_need_lead_time = round(velocity * lead_time)
        safety_stock = round(velocity * safety_stock_days)
        
        # Reorder quantity calculation including safety stock
        reorder_qty = max(forecast_30_qty + forecast_need_lead_time + safety_stock - (current_available + inbound_qty), 0)

        forecast_report.append([product_name, sku, round(reorder_qty), velocity, forecast_30_qty, current_available, inbound_qty, lead_time, safety_stock, forecast_need_lead_time])
        
        if reorder_qty > 0:
            reorder_report.append([product_name, sku, round(reorder_qty), current_available, inbound_qty, lead_time, safety_stock, forecast_30_qty])

    forecast_df = pd.DataFrame(forecast_report, columns=[
        'Product', 'SKU', 'Qty to Reorder Now', 'Sales Velocity', 'Forecast Sales Qty (30 Days)', 'Current Available Stock', 
        'Inbound Stock', 'Lead Time (Days)', 'Safety Stock', 'Forecast Inventory Need (With Lead Time)'
    ])
    
    reorder_df = pd.DataFrame(reorder_report, columns=[
        'Product', 'SKU', 'Qty to Reorder Now', 'Current Available Stock', 'Inbound Stock', 'Lead Time (Days)', 
        'Safety Stock', 'Forecast Sales Qty (30 Days)'
    ])

    # Ensure relevant columns are integers
    forecast_df[['Qty to Reorder Now', 'Forecast Sales Qty (30 Days)', 'Current Available Stock', 
                 'Inbound Stock', 'Lead Time (Days)', 'Safety Stock', 'Forecast Inventory Need (With Lead Time)']] = forecast_df[[
        'Qty to Reorder Now', 'Forecast Sales Qty (30 Days)', 'Current Available Stock', 
        'Inbound Stock', 'Lead Time (Days)', 'Safety Stock', 'Forecast Inventory Need (With Lead Time)'
    ]].astype(int)

    reorder_df[['Qty to Reorder Now', 'Current Available Stock', 'Inbound Stock', 'Lead Time (Days)', 
                'Safety Stock', 'Forecast Sales Qty (30 Days)']] = reorder_df[[
        'Qty to Reorder Now', 'Current Available Stock', 'Inbound Stock', 'Lead Time (Days)', 
        'Safety Stock', 'Forecast Sales Qty (30 Days)'
    ]].astype(int)

    return forecast_df, reorder_df

def to_excel(forecast_df, reorder_df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # Write forecast and reorder dataframes to separate sheets
        forecast_df.to_excel(writer, index=False, sheet_name='Forecast')
        reorder_df.to_excel(writer, index=False, sheet_name='Reorder')

        # Access the workbook and the worksheets
        workbook = writer.book
        forecast_sheet = writer.sheets['Forecast']
        reorder_sheet = writer.sheets['Reorder']

        # Format the sheets as tables
        for worksheet, df in zip([forecast_sheet, reorder_sheet], [forecast_df, reorder_df]):
            (max_row, max_col) = df.shape
            worksheet.add_table(0, 0, max_row, max_col - 1, {
                'columns': [{'header': column} for column in df.columns],
                'style': 'Table Style Medium 2'
            })

            # Auto-size the columns
            for i, col in enumerate(df.columns):
                column_len = df[col].astype(str).map(len).max()
                worksheet.set_column(i, i, column_len + 2)  # Adjust the width

        # Highlight the "Qty to Reorder Now" column in a different color
        reorder_col_index = reorder_df.columns.get_loc("Qty to Reorder Now")
        reorder_sheet.set_column(reorder_col_index, reorder_col_index, None, workbook.add_format({'bg_color': '#FFC7CE'}))

    processed_data = output.getvalue()
    return processed_data

def plot_top_sellers(sales_data, inventory_data):
    top_sellers = sales_data.groupby('variant_sku')['net_quantity'].sum().sort_values(ascending=False).head(10)
    top_sellers = top_sellers.reset_index()
    top_sellers = top_sellers.merge(inventory_data[['Part No.', 'Available']], left_on='variant_sku', right_on='Part No.', how='left')
    
    fig, ax = plt.subplots()
    ax.barh(top_sellers['variant_sku'], top_sellers['net_quantity'], color='skyblue', label='Total Sold (90 Days)')
    ax.barh(top_sellers['variant_sku'], top_sellers['Available'], color='orange', label='Current Available Stock')
    
    ax.set_xlabel('Quantity')
    ax.set_title('Top 10 Selling Products and Their Inventory Condition')
    ax.invert_yaxis()
    ax.legend()
    
    return fig

# Streamlit app
st.title("Reorder Report Generator (90 Days Sales)")

# Add tooltips to provide guidance on file uploads
st.sidebar.header("Upload Data")

sales_file = st.sidebar.file_uploader("Upload 90-Day Sales Data (CSV)", type="csv",
                                      help="Upload the 'Forecast 90' Shopify report. This file should contain columns such as 'variant_sku' and 'net_quantity'.")

inventory_file = st.sidebar.file_uploader("Upload Inventory Data (CSV)", type="csv",
                                          help="Upload the inventory data file. This file should include columns such as 'Part No.', 'Available', 'Expected, available', and 'Lead time'.")

# Add a slider for safety stock
safety_stock_days = st.sidebar.slider(
    "Safety Stock (in days)", 
    min_value=0, 
    max_value=30, 
    value=7, 
    help="Adjust the safety stock buffer. The default is 7 days."
)

# Logic to handle file uploads and report generation
if sales_file and inventory_file:
    sales_data = pd.read_csv(sales_file)
    inventory_data = pd.read_csv(inventory_file)
    
    # Generate and display top sellers chart
    st.subheader("Top 10 Selling Products and Their Inventory Condition")
    top_sellers_fig = plot_top_sellers(sales_data, inventory_data)
    st.pyplot(top_sellers_fig)
    
    if st.sidebar.button("Generate Reorder Report"):
        forecast_df, reorder_df = generate_report(sales_data, inventory_data, safety_stock_days)
        
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
