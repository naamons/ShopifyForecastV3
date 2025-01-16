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

# Function to initialize MPS dataframe
def initialize_mps():
    # Create an empty DataFrame with the desired columns
    columns = [
        'Product', 'SKU', 'Current Available Stock', 'In Transit Units',
        'Lead Time (Days)', 'Shipping Time (Days)', 'Sales Velocity (units/day)',
        'Qty to Order Each Month'
    ]
    mps_df = pd.DataFrame(columns=columns)
    return mps_df

# Function to suggest products based on velocity and potential stockouts
def suggest_products(sales_velocity, inventory_data, threshold=0.7, safety_stock_days=7):
    suggestions = []
    for sku, velocity in sales_velocity.items():
        if velocity < threshold:
            continue  # Skip products below the velocity threshold
        inventory_row = inventory_data[inventory_data['Part No.'] == sku]
        if inventory_row.empty:
            continue
        current_stock = inventory_row['Available'].values[0]
        in_transit = inventory_row['Expected, available'].values[0]
        lead_time = inventory_row['Lead time'].fillna(30).astype(int).values[0]
        safety_stock = math.ceil(velocity * safety_stock_days)
        total_available = current_stock + in_transit
        # Calculate demand during lead time
        demand_during_lead = velocity * lead_time
        if total_available < demand_during_lead + safety_stock:
            product_name = inventory_row['Part description'].values[0]
            suggestions.append({
                'Product': product_name,
                'SKU': sku,
                'Current Available Stock': current_stock,
                'In Transit Units': in_transit,
                'Lead Time (Days)': lead_time,
                'Sales Velocity (units/day)': velocity
            })
    return suggestions

# Function to generate procurement plan based on MPS
def generate_procurement_plan(mps_df, safety_stock_days=7):
    plan = []
    for idx, row in mps_df.iterrows():
        product = row['Product']
        sku = row['SKU']
        current_stock = row['Current Available Stock']
        in_transit = row['In Transit Units']
        lead_time = row['Lead Time (Days)']
        shipping_time = row['Shipping Time (Days)']
        velocity = row['Sales Velocity (units/day)']
        qty_to_order = row['Qty to Order Each Month']

        total_available = current_stock + in_transit
        # Calculate total demand over lead time plus safety stock
        demand = velocity * lead_time
        safety_stock = velocity * safety_stock_days

        # Calculate reorder quantity
        reorder_qty = max(demand + safety_stock - total_available, 0)

        plan.append({
            'Product': product,
            'SKU': sku,
            'Qty to Order': reorder_qty,
            'Safety Stock': safety_stock,
            'Demand During Lead Time': demand,
            'Total Available': total_available
        })

    plan_df = pd.DataFrame(plan)
    return plan_df

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

# Add sliders for safety stock and velocity threshold
safety_stock_days = st.sidebar.slider(
    "Safety Stock (in days)",
    min_value=0,
    max_value=30,
    value=7,
    help="Adjust the safety stock buffer. The default is 7 days."
)

velocity_threshold = st.sidebar.slider(
    "High Velocity Threshold (units/day)",
    min_value=0.0,
    max_value=5.0,
    value=0.7,
    step=0.1,
    help="Set the minimum sales velocity to consider a product as high velocity. The default is 0.7 units/day."
)

# Read the uploaded files into DataFrames once
if sales_file and inventory_file:
    # Reset file pointers before reading
    sales_file.seek(0)
    inventory_file.seek(0)

    # Read the files
    sales_data = pd.read_csv(sales_file)
    inventory_data = pd.read_csv(inventory_file)

    # **Add 'Procurement Type' to inventory_data here to avoid KeyError**
    if 'Is procured item' in inventory_data.columns:
        inventory_data['Procurement Type'] = inventory_data['Is procured item'].apply(lambda x: 'Purchased' if x == 1 else 'Manufactured')
    else:
        # Handle cases where 'Is procured item' is missing
        st.sidebar.warning("'Is procured item' column not found in Inventory Data. Setting 'Procurement Type' to 'Unknown' for all items.")
        inventory_data['Procurement Type'] = 'Unknown'

    # Calculate sales velocity
    sales_velocity = calculate_sales_velocity_90days(sales_data)

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
            st.session_state.mps_df = initialize_mps()

        mps_df = st.session_state.mps_df

        # Section: Suggest Products to Add
        st.subheader("Suggest Products to Add to MPS")

        if st.button("Suggest and Add All High Velocity Products"):
            suggestions = suggest_products(
                sales_velocity,
                inventory_data,
                threshold=velocity_threshold,
                safety_stock_days=safety_stock_days
            )

            if suggestions:
                # Convert suggestions to DataFrame
                suggestions_df = pd.DataFrame(suggestions)

                # Add suggestions to MPS
                st.session_state.mps_df = pd.concat([st.session_state.mps_df, suggestions_df], ignore_index=True)

                st.success(f"Added {len(suggestions)} products to the MPS table.")
            else:
                st.info("No products meet the criteria for addition to MPS.")

        # Section: Display MPS Table (Editable)
        st.subheader("Master Procurement Schedule (Editable)")

        if not st.session_state.mps_df.empty:
            # Configure AgGrid options
            gb = GridOptionsBuilder.from_dataframe(st.session_state.mps_df)
            gb.configure_default_column(editable=True, resizable=True)
            # Make certain columns non-editable
            gb.configure_columns(['Product', 'SKU', 'Sales Velocity (units/day)'], editable=False, pinned='left')
            grid_options = gb.build()

            grid_response = AgGrid(
                st.session_state.mps_df,
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

            # Update session state with edited data
            if edited_mps_df.equals(st.session_state.mps_df):
                pass  # No changes made
            else:
                st.session_state.mps_df = edited_mps_df

            # Section: Generate Procurement Plan
            st.subheader("Generate Procurement Plan")

            if st.button("Generate Procurement Plan"):
                procurement_plan = generate_procurement_plan(st.session_state.mps_df, safety_stock_days)

                if not procurement_plan.empty:
                    st.write("### Procurement Plan")
                    st.dataframe(procurement_plan)

                    # Download button for procurement plan
                    excel_data_plan = BytesIO()
                    with pd.ExcelWriter(excel_data_plan, engine='xlsxwriter') as writer:
                        procurement_plan.to_excel(writer, index=False, sheet_name='Procurement Plan')
                        workbook = writer.book
                        worksheet = writer.sheets['Procurement Plan']
                        # Auto-adjust column widths
                        for i, col in enumerate(procurement_plan.columns):
                            column_len = procurement_plan[col].astype(str).map(len).max()
                            worksheet.set_column(i, i, max(column_len + 2, 15))
                    excel_data_plan.seek(0)

                    st.download_button(
                        label="Download Procurement Plan as Excel",
                        data=excel_data_plan,
                        file_name='Procurement_Plan.xlsx',
                        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    )
                else:
                    st.info("Procurement plan is empty. Please ensure MPS table is populated correctly.")

        else:
            st.info("MPS table is currently empty. Use the 'Suggest and Add All High Velocity Products' button to populate the table.")

    else:
        st.warning("Please upload both 90-Day Sales and Inventory CSV files to proceed.")
