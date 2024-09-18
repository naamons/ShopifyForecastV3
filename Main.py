import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
import logging
from datetime import datetime
import math

def calculate_sales_velocity_90days(sales_data):
    sales_data['Total Quantity'] = sales_data['net_quantity']
    sales_velocity = sales_data.groupby('variant_sku')['Total Quantity'].sum() / 90  # Average daily sales over 90 days
    return sales_velocity

def generate_forecast(sales_velocity, days=30):
    return sales_velocity * days  # Forecasting based on current velocity

def generate_report(sales_data, inventory_data, safety_stock_days):
    sales_velocity = calculate_sales_velocity_90days(sales_data)
    forecast_30 = generate_forecast(sales_velocity, 30)

    # Filter out discontinued items
    active_inventory = inventory_data[inventory_data['Group name'] != 'Discontinued']

    # Impute lead time: Assume 30 days where lead time is missing
    active_inventory['Lead time'] = active_inventory['Lead time'].fillna(30)

    # Fill missing costs with 0
    active_inventory['Cost'] = active_inventory['Cost'].fillna(0)

    forecast_report = []
    reorder_report = []
    total_reorder_cost = 0  # Initialize total reorder cost

    # Convert "Is procured item" from 0/1 to text
    if 'Is procured item' in active_inventory.columns:
        active_inventory['Procurement Type'] = active_inventory['Is procured item'].apply(lambda x: 'Purchased' if x == 1 else 'Manufactured')
    else:
        active_inventory['Procurement Type'] = 'Unknown'

    for sku in active_inventory['Part No.']:
        product_name = active_inventory.loc[active_inventory['Part No.'] == sku, 'Part description'].values[0]
        velocity = sales_velocity.get(sku, 0)
        if velocity <= 0:
            continue  # Skip SKUs with no sales activity

        forecast_30_qty = round(forecast_30.get(sku, 0))
        current_available = active_inventory.loc[active_inventory['Part No.'] == sku, 'Available'].values[0]
        inbound_qty = active_inventory.loc[active_inventory['Part No.'] == sku, 'Expected, available'].values[0]
        lead_time = active_inventory.loc[active_inventory['Part No.'] == sku, 'Lead time'].values[0]
        cost = active_inventory.loc[active_inventory['Part No.'] == sku, 'Cost'].values[0]
        is_procured_text = active_inventory.loc[active_inventory['Part No.'] == sku, 'Procurement Type'].values[0]

        # Forecasted inventory need including lead time and safety stock
        forecast_need_lead_time = round(velocity * lead_time)
        safety_stock = round(velocity * safety_stock_days)
        
        # Reorder quantity calculation including safety stock
        reorder_qty = max(forecast_30_qty + forecast_need_lead_time + safety_stock - (current_available + inbound_qty), 0)
        reorder_cost = reorder_qty * cost

        # Add the reorder cost to the total
        total_reorder_cost += reorder_cost

        forecast_report.append([product_name, sku, round(reorder_qty), velocity, forecast_30_qty, current_available, inbound_qty, lead_time, safety_stock, forecast_need_lead_time, reorder_cost, cost, is_procured_text])
        
        if reorder_qty > 0:
            reorder_report.append([product_name, sku, round(reorder_qty), current_available, inbound_qty, lead_time, safety_stock, forecast_30_qty, reorder_cost, cost, is_procured_text])

    forecast_df = pd.DataFrame(forecast_report, columns=[
        'Product', 'SKU', 'Qty to Reorder Now', 'Sales Velocity', 'Forecast Sales Qty (30 Days)', 'Current Available Stock', 
        'Inbound Stock', 'Lead Time (Days)', 'Safety Stock', 'Forecast Inventory Need (With Lead Time)', 'Reorder Cost', 'Cost per Unit', 'Procurement Type'
    ])
    
    reorder_df = pd.DataFrame(reorder_report, columns=[
        'Product', 'SKU', 'Qty to Reorder Now', 'Current Available Stock', 'Inbound Stock', 'Lead Time (Days)', 
        'Safety Stock', 'Forecast Sales Qty (30 Days)', 'Reorder Cost', 'Cost per Unit', 'Procurement Type'
    ])

    # Ensure relevant columns are integers where applicable
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

    return forecast_df, reorder_df, total_reorder_cost

def to_excel(forecast_df, reorder_df, total_reorder_cost):
    # Set up basic logging
    logging.basicConfig(level=logging.INFO)

    # Ensure total_reorder_cost is a number (float or int)
    if total_reorder_cost is None or (isinstance(total_reorder_cost, float) and np.isnan(total_reorder_cost)):
        logging.warning("Total reorder cost is None or NaN. Defaulting to 0.0")
        total_reorder_cost = 0.0  # Default to 0 if None or NaN
    elif not isinstance(total_reorder_cost, (int, float)):
        try:
            total_reorder_cost = float(total_reorder_cost)
        except ValueError:
            logging.error(f"Unable to convert total_reorder_cost to float. Value: {total_reorder_cost}")
            total_reorder_cost = 0.0  # Default to 0 if conversion fails
    
    logging.info(f"Total Reorder Cost: {total_reorder_cost}")

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

        # Write the total reorder cost at the top of the Reorder sheet
        reorder_sheet.write(0, max_col, 'Total Reorder Cost')
        reorder_sheet.write(1, max_col, total_reorder_cost)

    processed_data = output.getvalue()
    return processed_data

# Streamlit app
st.title("Inventory Management System")

# Add tabs
tabs = st.tabs(["Reorder Report", "Master Procurement Schedule"])

# Common file uploaders for both tabs
st.sidebar.header("Upload Data")

sales_file = st.sidebar.file_uploader("Upload 90-Day Sales Data (CSV)", type="csv",
                                      help="Upload the 'Forecast 90' Shopify report. This file should contain columns such as 'variant_sku' and 'net_quantity'.")

inventory_file = st.sidebar.file_uploader("Upload Inventory Data (CSV)", type="csv",
                                          help="Upload the inventory data file. This file should include columns such as 'Part No.', 'Available', 'Expected, available', 'Cost', 'Lead time', and 'Group name'.")

# Add a slider for safety stock
safety_stock_days = st.sidebar.slider(
    "Safety Stock (in days)", 
    min_value=0, 
    max_value=30, 
    value=7, 
    help="Adjust the safety stock buffer. The default is 7 days."
)

# Read the uploaded files into DataFrames once
if sales_file and inventory_file:
    # Reset file pointers before reading (optional but good practice)
    sales_file.seek(0)
    inventory_file.seek(0)
    
    # Read the files
    sales_data = pd.read_csv(sales_file)
    inventory_data = pd.read_csv(inventory_file)
else:
    sales_data = None
    inventory_data = None

# Tab 1: Reorder Report (existing functionality)
with tabs[0]:
    st.header("Reorder Report Generator (90 Days Sales)")
    if sales_data is not None and inventory_data is not None:
        if st.sidebar.button("Generate Reorder Report"):
            forecast_df, reorder_df, total_reorder_cost = generate_report(sales_data, inventory_data, safety_stock_days)
            
            if forecast_df is not None and reorder_df is not None:
                st.subheader("Forecast Report")
                st.dataframe(forecast_df)
                
                st.subheader("Reorder Report")
                st.dataframe(reorder_df)
                
                # Display total reorder cost at the top of the report
                st.write(f"**Total Reorder Cost:** ${total_reorder_cost:,.2f}")
                
                excel_data = to_excel(forecast_df, reorder_df, total_reorder_cost)
                st.download_button(
                    label="Download Report as Excel",
                    data=excel_data,
                    file_name='Reorder_Report.xlsx',
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                )
    else:
        st.warning("Please upload both 90-Day Sales and Inventory CSV files to proceed.")

# Tab 2: Master Procurement Schedule
with tabs[1]:
    st.header("Master Procurement Schedule (MPS)")
    if inventory_data is not None and sales_data is not None:
        # Filter out discontinued items
        active_inventory = inventory_data[inventory_data['Group name'] != 'Discontinued']
        
        # Convert "Is procured item" from 0/1 to text
        if 'Is procured item' in active_inventory.columns:
            active_inventory['Procurement Type'] = active_inventory['Is procured item'].apply(lambda x: 'Purchased' if x == 1 else 'Manufactured')
        else:
            active_inventory['Procurement Type'] = 'Unknown'
        
        # Filter to include only procured items
        procured_inventory = active_inventory[active_inventory['Procurement Type'] == 'Purchased']
        
        # Calculate sales velocity
        sales_velocity = calculate_sales_velocity_90days(sales_data)
        
        # Filter procured_inventory to include only items with demand
        procured_inventory['Part No.'] = procured_inventory['Part No.'].astype(str)
        skus_with_demand = sales_velocity[sales_velocity > 0].index.tolist()
        procured_inventory_with_demand = procured_inventory[procured_inventory['Part No.'].isin(skus_with_demand)]
        
        # Prepare the MPS dataframe
        mps_df = procured_inventory_with_demand[['Part description', 'Part No.', 'Available', 'Lead time']].copy()
        mps_df.rename(columns={'Product description': 'Product', 'Part description': 'Product', 'Part No.': 'SKU', 'Available': 'Current Available Stock', 'Lead time': 'Lead Time (Days)'}, inplace=True)
        
        # Convert Lead Time to integer
        mps_df['Lead Time (Days)'] = mps_df['Lead Time (Days)'].fillna(30).astype(int)
        
        # Generate list of months and days
        from datetime import datetime

        # Get current date
        current_date = datetime.now()

        # Generate list of months for the next 6 months
        months = pd.date_range(current_date, periods=6, freq='MS').to_pydatetime().tolist()

        # For each month, get the month name and year
        month_names = [month.strftime("%B %Y") for month in months]

        # For each month, get the number of days in the month
        number_of_days_in_month = [pd.Period(month.strftime("%Y-%m")).days_in_month for month in months]
        
        # Calculate forecasted demand per month based on sales velocity
        for i, month_name in enumerate(month_names):
            days_in_month = number_of_days_in_month[i]
            mps_df[month_name] = mps_df['SKU'].apply(lambda sku: round(sales_velocity.get(sku, 0) * days_in_month))
        
        # Allow users to add new products
        st.subheader("Add New Products to MPS")
        # Get list of products not already in MPS
        skus_in_mps = mps_df['SKU'].tolist()
        available_new_products = procured_inventory[~procured_inventory['Part No.'].isin(skus_in_mps)]
        available_new_products = available_new_products[['Part description', 'Part No.']].rename(columns={'Part description': 'Product', 'Part No.': 'SKU'})
        
        # User selects products to add
        selected_products = st.multiselect("Select products to add to MPS", options=available_new_products['SKU'], format_func=lambda x: f"{x} - {available_new_products[available_new_products['SKU']==x]['Product'].values[0]}")
        
        if st.button("Add Selected Products"):
            for sku in selected_products:
                product_info = available_new_products[available_new_products['SKU'] == sku].iloc[0]
                # Get other required fields from procured_inventory
                product_row = procured_inventory[procured_inventory['Part No.'] == sku].iloc[0]
                new_row = {
                    'Product': product_info['Product'],
                    'SKU': sku,
                    'Current Available Stock': product_row.get('Available', 0),
                    'Lead Time (Days)': int(product_row.get('Lead time', 30))
                }
                # Initialize demand to 0 for all months
                for month_name in month_names:
                    new_row[month_name] = 0
                # Append the new row to mps_df using pd.concat()
                new_row_df = pd.DataFrame([new_row])
                mps_df = pd.concat([mps_df, new_row_df], ignore_index=True)
        
        # Reset index to avoid any issues
        mps_df.reset_index(drop=True, inplace=True)
        
        # Allow users to adjust the demand
        st.subheader("Forecasted Demand (Editable)")
        editable_mps_df = st.data_editor(mps_df)

        # Calculate total adjusted demand over next 6 months
        editable_mps_df['Total Demand'] = editable_mps_df[month_names].sum(axis=1)
        
        # Calculate "How Many to Purchase" for each month based on lead time
        # Calculate LeadTimeMonths
        editable_mps_df['LeadTimeMonths'] = editable_mps_df['Lead Time (Days)'].apply(lambda x: math.ceil(x / 30))

        # Initialize Purchase Qty columns
        for month_name in month_names:
            editable_mps_df[f'Purchase Qty {month_name}'] = 0

        # For each SKU, calculate Purchase Qty per month
        for idx, row in editable_mps_df.iterrows():
            lead_time_months = int(row['LeadTimeMonths'])
            current_available_stock = row['Current Available Stock']
            cumulative_demand = 0
            for i, month_name in enumerate(month_names):
                demand_qty = row[month_name]
                cumulative_demand += demand_qty
                purchase_month_index = i - lead_time_months
                if purchase_month_index >= 0:
                    purchase_month_name = month_names[purchase_month_index]
                    # Accumulate purchase quantities
                    existing_qty = editable_mps_df.at[idx, f'Purchase Qty {purchase_month_name}']
                    editable_mps_df.at[idx, f'Purchase Qty {purchase_month_name}'] = existing_qty + demand_qty
                else:
                    # Need to purchase in the first month
                    existing_qty = editable_mps_df.at[idx, f'Purchase Qty {month_names[0]}']
                    editable_mps_df.at[idx, f'Purchase Qty {month_names[0]}'] = existing_qty + demand_qty

            # Adjust Purchase Qty in first month for current available stock
            first_month_purchase_qty = editable_mps_df.at[idx, f'Purchase Qty {month_names[0]}']
            adjusted_purchase_qty = max(first_month_purchase_qty - current_available_stock, 0)
            editable_mps_df.at[idx, f'Purchase Qty {month_names[0]}'] = adjusted_purchase_qty

        # Display the adjusted demand with "How Many to Purchase" columns
        st.subheader("Adjusted Demand with Purchase Quantities")
        st.write(editable_mps_df)
        
        # Allow download to Excel
        def mps_to_excel(df):
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='MPS')
                
                # Get the xlsxwriter workbook and worksheet objects.
                workbook = writer.book
                worksheet = writer.sheets['MPS']
                
                # Format the columns.
                format1 = workbook.add_format({'num_format': '#,##0'})
                worksheet.set_column(0, len(df.columns)-1, 15, format1)
                
            processed_data = output.getvalue()
            return processed_data
        
        excel_data = mps_to_excel(editable_mps_df)
        
        st.download_button(
            label="Download MPS as Excel",
            data=excel_data,
            file_name='MPS.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        
    else:
        st.warning("Please upload both 90-Day Sales and Inventory CSV files to proceed.")
