import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
import logging
from datetime import datetime
import math
from st_aggrid import AgGrid, GridOptionsBuilder, DataReturnMode, GridUpdateMode

# Configure logging
logging.basicConfig(level=logging.INFO)

# Function to calculate sales velocity over 90 days
def calculate_sales_velocity_90days(sales_data):
    sales_data['Total Quantity'] = sales_data['Net items sold']
    sales_velocity = sales_data.groupby('Product variant SKU')['Total Quantity'].sum() / 90  # Average daily sales over 90 days
    return sales_velocity

# Function to generate forecast based on sales velocity
def generate_forecast(sales_velocity, days=30):
    return sales_velocity * days  # Forecasting based on current velocity

# Function to generate reorder and forecast reports
def generate_report(sales_data, inventory_data, safety_stock_days):
    sales_velocity = calculate_sales_velocity_90days(sales_data)
    forecast_30 = generate_forecast(sales_velocity, 30)

    # Filter out discontinued items
    active_inventory = inventory_data[inventory_data['Group name'] != 'Discontinued'].copy()

    # Impute lead time: Assume 30 days where lead time is missing
    active_inventory['Lead time'] = active_inventory['Lead time'].fillna(30)

    # Fill missing costs with 0
    active_inventory['Cost'] = active_inventory['Cost'].fillna(0)

    # Convert "Is procured item" from 0/1 to text
    if 'Is procured item' in active_inventory.columns:
        active_inventory['Procurement Type'] = active_inventory['Is procured item'].apply(lambda x: 'Purchased' if x == 1 else 'Manufactured')
    else:
        active_inventory['Procurement Type'] = 'Unknown'

    forecast_report = []
    reorder_report = []
    total_reorder_cost = 0  # Initialize total reorder cost

    for idx, row in active_inventory.iterrows():
        sku = row['Part No.']
        product_name = row['Part description']
        velocity = sales_velocity.get(sku, 0)
        if velocity <= 0:
            continue  # Skip SKUs with no sales activity

        forecast_30_qty = round(forecast_30.get(sku, 0))
        current_available = row['Available']
        inbound_qty = row['Expected, available']
        lead_time = row['Lead time']
        cost = row['Cost']
        procurement_type = row['Procurement Type']

        # Forecasted inventory need including lead time and safety stock
        forecast_need_lead_time = round(velocity * lead_time)
        safety_stock = round(velocity * safety_stock_days)

        # Reorder quantity calculation including safety stock
        reorder_qty = max(forecast_30_qty + forecast_need_lead_time + safety_stock - (current_available + inbound_qty), 0)
        reorder_cost = reorder_qty * cost

        # Add the reorder cost to the total
        total_reorder_cost += reorder_cost

        forecast_report.append([
            product_name, sku, reorder_qty, velocity, forecast_30_qty,
            current_available, inbound_qty, lead_time, safety_stock,
            forecast_need_lead_time, reorder_cost, cost, procurement_type
        ])

        if reorder_qty > 0:
            reorder_report.append([
                product_name, sku, reorder_qty, current_available,
                inbound_qty, lead_time, safety_stock, forecast_30_qty,
                reorder_cost, cost, procurement_type
            ])

    forecast_df = pd.DataFrame(forecast_report, columns=[
        'Product', 'SKU', 'Qty to Reorder Now', 'Sales Velocity',
        'Forecast Sales Qty (30 Days)', 'Current Available Stock',
        'Inbound Stock', 'Lead Time (Days)', 'Safety Stock',
        'Forecast Inventory Need (With Lead Time)', 'Reorder Cost',
        'Cost per Unit', 'Procurement Type'
    ])

    reorder_df = pd.DataFrame(reorder_report, columns=[
        'Product', 'SKU', 'Qty to Reorder Now', 'Current Available Stock',
        'Inbound Stock', 'Lead Time (Days)', 'Safety Stock',
        'Forecast Sales Qty (30 Days)', 'Reorder Cost',
        'Cost per Unit', 'Procurement Type'
    ])

    # Ensure relevant columns are integers where applicable
    int_columns_forecast = [
        'Qty to Reorder Now', 'Forecast Sales Qty (30 Days)',
        'Current Available Stock', 'Inbound Stock', 'Lead Time (Days)',
        'Safety Stock', 'Forecast Inventory Need (With Lead Time)'
    ]
    forecast_df[int_columns_forecast] = forecast_df[int_columns_forecast].astype(int)

    int_columns_reorder = [
        'Qty to Reorder Now', 'Current Available Stock',
        'Inbound Stock', 'Lead Time (Days)', 'Safety Stock',
        'Forecast Sales Qty (30 Days)'
    ]
    reorder_df[int_columns_reorder] = reorder_df[int_columns_reorder].astype(int)

    return forecast_df, reorder_df, total_reorder_cost

# Function to convert forecast and reorder dataframes to Excel
def to_excel(forecast_df, reorder_df, total_reorder_cost):
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

# Function to convert MPS dataframe to Excel
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

# Initialize session state for MPS if not already done
def initialize_mps(inventory_data, sales_data):
    # Filter out discontinued items
    active_inventory = inventory_data[inventory_data['Group name'] != 'Discontinued'].copy()

    # Convert "Is procured item" from 0/1 to text
    if 'Is procured item' in active_inventory.columns:
        active_inventory['Procurement Type'] = active_inventory['Is procured item'].apply(lambda x: 'Purchased' if x == 1 else 'Manufactured')
    else:
        active_inventory['Procurement Type'] = 'Unknown'

    # Filter to include only procured items
    procured_inventory = active_inventory[active_inventory['Procurement Type'] == 'Purchased'].copy()

    # Calculate sales velocity
    sales_velocity = calculate_sales_velocity_90days(sales_data)

    # Filter procured_inventory to include only items with demand
    procured_inventory['Part No.'] = procured_inventory['Part No.'].astype(str)
    skus_with_demand = sales_velocity[sales_velocity > 0].index.tolist()
    procured_inventory_with_demand = procured_inventory[procured_inventory['Part No.'].isin(skus_with_demand)].copy()

    # Prepare the MPS dataframe
    mps_df = procured_inventory_with_demand[['Part description', 'Part No.', 'Available', 'Expected, available', 'Lead time']].copy()
    mps_df.rename(columns={
        'Part description': 'Product',
        'Part No.': 'SKU',
        'Available': 'Current Available Stock',
        'Expected, available': 'Inbound Stock',
        'Lead time': 'Lead Time (Days)'
    }, inplace=True)

    # Convert Lead Time to integer
    mps_df['Lead Time (Days)'] = mps_df['Lead Time (Days)'].fillna(30).astype(int)

    # Initialize empty MPS dataframe
    mps_df = mps_df[['Product', 'SKU', 'Current Available Stock', 'Inbound Stock', 'Lead Time (Days)']].copy()

    # Add empty columns for future calculations
    mps_df['Qty to Reorder Now'] = 0
    mps_df['Reorder Cost'] = 0.0
    mps_df['Cost per Unit'] = 0.0

    return mps_df

# Streamlit app
st.title("Inventory Management System")

# Add tabs
tabs = st.tabs(["Reorder Report", "Master Procurement Schedule"])

# Common file uploaders for both tabs
st.sidebar.header("Upload Data")

sales_file = st.sidebar.file_uploader(
    "Upload 90-Day Sales Data (CSV)", type="csv",
    help="Upload the 'Forecast 90' Shopify report. This file should contain columns such as 'variant_sku' and 'net_quantity'."
)

inventory_file = st.sidebar.file_uploader(
    "Upload Inventory Data (CSV)", type="csv",
    help="Upload the inventory data file. This file should include columns such as 'Part No.', 'Available', 'Expected, available', 'Cost', 'Lead time', and 'Group name'."
)

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
    # Reset file pointers before reading
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
        if st.button("Generate Reorder Report"):
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
                    label="Download Reorder Report as Excel",
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
        # Initialize session state for MPS if it doesn't exist
        if 'mps_df' not in st.session_state:
            st.session_state.mps_df = initialize_mps(inventory_data, sales_data)
            st.session_state.suggestions = None  # To store product suggestions

        mps_df = st.session_state.mps_df

        # Suggest products to add based on sales velocity and stock levels
        def suggest_products(sales_velocity, inventory_data, lead_time_days, safety_stock_days):
            suggestions = []
            for sku, velocity in sales_velocity.items():
                if velocity <= 0:
                    continue
                inventory_row = inventory_data[inventory_data['Part No.'] == sku]
                if inventory_row.empty:
                    continue
                current_available = inventory_row['Available'].values[0]
                inbound_qty = inventory_row['Expected, available'].values[0]
                lead_time = inventory_row['Lead time'].fillna(30).astype(int).values[0]
                safety_stock = math.ceil(velocity * safety_stock_days)
                total_available = current_available + inbound_qty
                # Estimate when stock will run out
                days_until_out = (total_available - safety_stock) / velocity if velocity else float('inf')
                if days_until_out < lead_time:
                    product_name = inventory_row['Part description'].values[0]
                    suggestions.append(f"{sku} - {product_name}")
            return suggestions

        # Generate suggestions
        if st.button("Show Product Suggestions"):
            suggestions = suggest_products(
                calculate_sales_velocity_90days(sales_data),
                inventory_data,
                lead_time_days=30,  # You can adjust this as needed
                safety_stock_days=safety_stock_days
            )
            if suggestions:
                st.subheader("Suggested Products to Add")
                st.write("These products are selling well and may run out of stock before the lead time ends:")
                for product in suggestions:
                    st.write(f"- {product}")
                st.session_state.suggestions = suggestions
            else:
                st.write("No product suggestions at this time.")
                st.session_state.suggestions = []

        # Allow users to add products manually
        st.subheader("Add New Product to MPS")

        # Get list of products not already in MPS
        existing_skus = mps_df['SKU'].tolist()
        available_new_products = inventory_data[
            (inventory_data['Procurement Type'] == 'Purchased') &
            (~inventory_data['Part No.'].isin(existing_skus)) &
            (inventory_data['Group name'] != 'Discontinued')
        ][['Part description', 'Part No.', 'Available', 'Expected, available', 'Lead time']].copy()

        if not available_new_products.empty:
            new_product_sku = st.selectbox(
                "Select SKU to Add",
                options=available_new_products['Part No.'],
                format_func=lambda x: f"{x} - {available_new_products[new_product_sku == available_new_products['Part No.']]['Part description'].values[0]}"
            )

            # Fetch selected product details
            selected_product = available_new_products[available_new_products['Part No.'] == new_product_sku].iloc[0]

            with st.form("add_product_form"):
                new_product_name = selected_product['Part description']
                new_current_stock = int(selected_product['Available'])
                new_inbound_stock = int(selected_product['Expected, available'])
                new_lead_time = st.number_input(
                    "Lead Time (Days)",
                    min_value=1,
                    max_value=365,
                    value=int(selected_product['Lead time']) if not pd.isna(selected_product['Lead time']) else 30
                )
                new_cost = st.number_input(
                    "Cost per Unit",
                    min_value=0.0,
                    value=0.0,
                    step=0.01
                )
                submitted = st.form_submit_button("Add Product")

                if submitted:
                    new_row = {
                        'Product': new_product_name,
                        'SKU': new_product_sku,
                        'Current Available Stock': new_current_stock,
                        'Inbound Stock': new_inbound_stock,
                        'Lead Time (Days)': new_lead_time,
                        'Qty to Reorder Now': 0,
                        'Reorder Cost': 0.0,
                        'Cost per Unit': new_cost
                    }
                    mps_df = mps_df.append(new_row, ignore_index=True)
                    st.session_state.mps_df = mps_df
                    st.success(f"Added {new_product_name} to MPS.")
        else:
            st.info("No available products to add.")

        # Display and edit the MPS table
        st.subheader("Master Procurement Schedule (Editable)")

        # Configure AgGrid options
        gb = GridOptionsBuilder.from_dataframe(mps_df)
        gb.configure_default_column(editable=True, resizable=True)
        gb.configure_columns(['Product', 'SKU'], editable=False, pinned='left')  # Make Product and SKU non-editable
        grid_options = gb.build()

        grid_response = AgGrid(
            mps_df,
            gridOptions=grid_options,
            height=400,
            width='100%',
            data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
            update_mode=GridUpdateMode.MODEL_CHANGED,
            allow_unsafe_jscode=True,
            enable_enterprise_modules=False,
            fit_columns_on_grid_load=True
        )

        edited_mps_df = grid_response['data']
        edited_mps_df = pd.DataFrame(edited_mps_df)

        if st.button("Update MPS"):
            # Update session state with edited data
            st.session_state.mps_df = edited_mps_df

            # Recalculate reorder quantities and costs
            # Fetch sales velocity
            sales_velocity = calculate_sales_velocity_90days(sales_data)

            # Recalculate based on edited MPS
            for idx, row in edited_mps_df.iterrows():
                sku = row['SKU']
                velocity = sales_velocity.get(sku, 0)
                lead_time = row['Lead Time (Days)']
                current_available = row['Current Available Stock']
                inbound_stock = row['Inbound Stock']
                cost_per_unit = row['Cost per Unit']

                # Calculate safety stock
                safety_stock = math.ceil(velocity * safety_stock_days)

                # Calculate total available
                total_available = current_available + inbound_stock

                # Calculate reorder quantity
                forecast_need_lead_time = math.ceil(velocity * lead_time)
                forecast_30_qty = math.ceil(velocity * 30)
                reorder_qty = max(forecast_30_qty + forecast_need_lead_time + safety_stock - total_available, 0)
                reorder_cost = reorder_qty * cost_per_unit

                # Update the dataframe
                edited_mps_df.at[idx, 'Qty to Reorder Now'] = reorder_qty
                edited_mps_df.at[idx, 'Reorder Cost'] = reorder_cost

            # Update session state
            st.session_state.mps_df = edited_mps_df

            st.success("MPS updated with new reorder quantities and costs.")

        # Display the updated MPS
        st.subheader("Updated Master Procurement Schedule")
        st.dataframe(st.session_state.mps_df)

        # Allow download to Excel
        excel_data = mps_to_excel(st.session_state.mps_df)

        st.download_button(
            label="Download MPS as Excel",
            data=excel_data,
            file_name='MPS.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )

    else:
        st.warning("Please upload both 90-Day Sales and Inventory CSV files to proceed.")
