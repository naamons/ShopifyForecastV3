import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
import logging
import math
from st_aggrid import AgGrid, GridOptionsBuilder, DataReturnMode, GridUpdateMode

# ------------------------------
# Configure Logging
# ------------------------------
logging.basicConfig(level=logging.INFO)

# ------------------------------
# Utility Functions
# ------------------------------

def calculate_sales_velocity_90days(sales_data):
    """
    Calculate average daily sales velocity over 90 days.
    
    Parameters:
        sales_data (pd.DataFrame): Sales data containing 'Product variant SKU' and 'Net items sold'.
    
    Returns:
        pd.Series: Sales velocity indexed by SKU.
    """
    sales_data['Total Quantity'] = sales_data['Net items sold']
    sales_velocity = sales_data.groupby('Product variant SKU')['Total Quantity'].sum() / 90  # units/day
    return sales_velocity

def to_excel(df, sheet_name='Sheet1'):
    """
    Convert DataFrame to Excel format.
    
    Parameters:
        df (pd.DataFrame): DataFrame to convert.
        sheet_name (str): Name of the Excel sheet.
    
    Returns:
        bytes: Excel file in bytes.
    """
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
        workbook = writer.book
        worksheet = writer.sheets[sheet_name]
        # Auto-adjust column widths
        for idx, col in enumerate(df.columns):
            column_len = df[col].astype(str).map(len).max()
            worksheet.set_column(idx, idx, max(column_len + 2, 15))
    processed_data = output.getvalue()
    return processed_data

def initialize_mps():
    """
    Initialize an empty Master Procurement Schedule (MPS) DataFrame.
    
    Returns:
        pd.DataFrame: Empty MPS DataFrame with predefined columns.
    """
    columns = [
        'Product', 'SKU', 'Current Stock', 'In Transit Units',
        'Lead Time (Days)', 'Shipping Time (Days)', 'Sales Velocity (units/day)'
    ]
    mps_df = pd.DataFrame(columns=columns)
    return mps_df

def suggest_products(sales_velocity, inventory_data, threshold=0.7, safety_stock_days=7, include_all_high_velocity=False):
    """
    Suggest products based on sales velocity and potential stockouts.
    
    Parameters:
        sales_velocity (pd.Series): Sales velocity indexed by SKU.
        inventory_data (pd.DataFrame): Inventory data containing 'Part No.', 'Available', 'Expected, available', etc.
        threshold (float): Minimum sales velocity to consider a product as high velocity.
        safety_stock_days (int): Number of days to maintain as safety stock.
        include_all_high_velocity (bool): If True, include all high-velocity products regardless of stockout risk.
    
    Returns:
        list of dict: List containing product details for suggestions.
    """
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

        if include_all_high_velocity:
            # Suggest all high-velocity products
            product_name = inventory_row['Part description'].values[0]
            suggestions.append({
                'Product': product_name,
                'SKU': sku,
                'Current Stock': current_stock,
                'In Transit Units': in_transit,
                'Lead Time (Days)': lead_time,
                'Shipping Time (Days)': 0,  # Default value, user can edit
                'Sales Velocity (units/day)': velocity
            })
        else:
            # Only suggest if at risk of stockout
            if total_available < demand_during_lead + safety_stock:
                product_name = inventory_row['Part description'].values[0]
                suggestions.append({
                    'Product': product_name,
                    'SKU': sku,
                    'Current Stock': current_stock,
                    'In Transit Units': in_transit,
                    'Lead Time (Days)': lead_time,
                    'Shipping Time (Days)': 0,  # Default value, user can edit
                    'Sales Velocity (units/day)': velocity
                })
    return suggestions

def generate_procurement_plan(mps_df, safety_stock_days=7, months_ahead=12):
    """
    Generate a monthly procurement plan for each product in MPS.
    
    Parameters:
        mps_df (pd.DataFrame): Master Procurement Schedule DataFrame.
        safety_stock_days (int): Number of days to maintain as safety stock.
        months_ahead (int): Number of months ahead to generate the plan for.
    
    Returns:
        pd.DataFrame: Procurement plan detailing orders per month.
    """
    plan = []

    for idx, row in mps_df.iterrows():
        product = row['Product']
        sku = row['SKU']
        current_stock = row['Current Stock']
        in_transit = row['In Transit Units']
        lead_time = row['Lead Time (Days)']
        shipping_time = row['Shipping Time (Days)']
        velocity = row['Sales Velocity (units/day)']

        # Total available stock
        total_available = current_stock + in_transit

        # Safety stock
        safety_stock = math.ceil(velocity * safety_stock_days)

        # Total demand during lead time
        demand_during_lead = math.ceil(velocity * lead_time)

        # Total required stock to avoid stockout
        required_stock = demand_during_lead + safety_stock

        # Initial order to cover lead time and safety stock
        initial_order = max(required_stock - total_available, 0)

        # Calculate order frequency based on lead time
        order_frequency = math.ceil(lead_time / 30)  # in months

        # Quantity to order each time
        order_qty = required_stock

        # Generate orders over the specified months
        for month in range(1, months_ahead + 1):
            if month % order_frequency == 0:
                plan.append({
                    'Product': product,
                    'SKU': sku,
                    'Month': f'Month {month}',
                    'Qty to Order': order_qty
                })

    plan_df = pd.DataFrame(plan)
    return plan_df

def generate_report(sales_data, inventory_data, safety_stock_days):
    """
    Generate forecast and reorder reports based on sales and inventory data.
    
    Parameters:
        sales_data (pd.DataFrame): Sales data containing 'Product variant SKU' and 'Net items sold'.
        inventory_data (pd.DataFrame): Inventory data containing 'Part No.', 'Available', 'Expected, available', etc.
        safety_stock_days (int): Number of days to maintain as safety stock.
    
    Returns:
        tuple: Forecast DataFrame, Reorder DataFrame, Total Reorder Cost.
    """
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

# ------------------------------
# Streamlit App
# ------------------------------

def main():
    # Set page configuration
    st.set_page_config(page_title="Inventory Management System", layout="wide")
    st.title("Inventory Management System")

    # Add tabs
    tabs = st.tabs(["Reorder Report", "Master Procurement Schedule"])

    # ------------------------------
    # Sidebar: Upload Data and Settings
    # ------------------------------
    st.sidebar.header("Upload Data & Settings")

    # File uploaders
    sales_file = st.sidebar.file_uploader(
        "Upload 90-Day Sales Data (CSV)", type="csv",
        help="Upload the 'Forecast 90' Shopify report. This file should contain columns such as 'Product variant SKU' and 'Net items sold'."
    )

    inventory_file = st.sidebar.file_uploader(
        "Upload Inventory Data (CSV)", type="csv",
        help="Upload the inventory data file. This file should include columns such as 'Part No.', 'Available', 'Expected, available', 'Cost', 'Lead time', and 'Group name'."
    )

    # Sliders for safety stock and velocity threshold
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
        max_value=10.0,
        value=0.7,
        step=0.1,
        help="Set the minimum sales velocity to consider a product as high velocity. The default is 0.7 units/day."
    )

    # Checkbox to include all high-velocity products
    include_all_high_velocity = st.sidebar.checkbox(
        "Include All High-Velocity Products",
        value=False,
        help="If checked, all high-velocity products will be suggested regardless of current stock levels."
    )

    # ------------------------------
    # Load Data
    # ------------------------------
    if sales_file and inventory_file:
        # Reset file pointers before reading
        sales_file.seek(0)
        inventory_file.seek(0)

        # Read the files
        try:
            sales_data = pd.read_csv(sales_file)
            inventory_data = pd.read_csv(inventory_file)
        except Exception as e:
            st.sidebar.error(f"Error reading files: {e}")
            sales_data = None
            inventory_data = None

        # Add 'Procurement Type' to inventory_data to avoid KeyError
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
        sales_velocity = None

    # ------------------------------
    # Tab 1: Reorder Report
    # ------------------------------
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

                    # Provide download buttons
                    forecast_excel = to_excel(forecast_df, sheet_name='Forecast')
                    reorder_excel = to_excel(reorder_df, sheet_name='Reorder')

                    st.download_button(
                        label="Download Forecast Report as Excel",
                        data=forecast_excel,
                        file_name='Forecast_Report.xlsx',
                        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    )

                    st.download_button(
                        label="Download Reorder Report as Excel",
                        data=reorder_excel,
                        file_name='Reorder_Report.xlsx',
                        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    )
        else:
            st.warning("Please upload both 90-Day Sales and Inventory CSV files to proceed.")

    # ------------------------------
    # Tab 2: Master Procurement Schedule
    # ------------------------------
    with tabs[1]:
        st.header("Master Procurement Schedule (MPS)")

        if inventory_data is not None and sales_data is not None:
            # Initialize session state for MPS if it doesn't exist
            if 'mps_df' not in st.session_state:
                st.session_state.mps_df = initialize_mps()

            mps_df = st.session_state.mps_df

            # Section: Suggest Products to Add
            st.subheader("Suggest High-Velocity Products to Add to MPS")

            if st.button("Suggest and Add All High Velocity Products"):
                suggestions = suggest_products(
                    sales_velocity,
                    inventory_data,
                    threshold=velocity_threshold,
                    safety_stock_days=safety_stock_days,
                    include_all_high_velocity=include_all_high_velocity
                )

                if suggestions:
                    # Convert suggestions to DataFrame
                    suggestions_df = pd.DataFrame(suggestions)

                    # Avoid duplicates
                    existing_skus = mps_df['SKU'].tolist()
                    suggestions_df = suggestions_df[~suggestions_df['SKU'].isin(existing_skus)]

                    if not suggestions_df.empty:
                        # Add suggestions to MPS
                        st.session_state.mps_df = pd.concat([mps_df, suggestions_df], ignore_index=True)
                        mps_df = st.session_state.mps_df

                        st.success(f"Added {len(suggestions_df)} products to the MPS table.")
                    else:
                        st.info("All suggested products are already in the MPS table.")
                else:
                    st.info("No products meet the criteria for addition to MPS.")

            # Section: Display and Edit MPS Table
            st.subheader("Master Procurement Schedule (Editable)")

            if not mps_df.empty:
                # Configure AgGrid options
                gb = GridOptionsBuilder.from_dataframe(mps_df)
                gb.configure_default_column(editable=True, resizable=True)
                # Make certain columns non-editable
                gb.configure_columns(['Product', 'SKU', 'Sales Velocity (units/day)'], editable=False, pinned='left')
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

                # Update session state with edited data if changes were made
                if not edited_mps_df.equals(st.session_state.mps_df):
                    st.session_state.mps_df = edited_mps_df
                    st.success("MPS table updated successfully.")

                # Update local variable
                mps_df = st.session_state.mps_df

                # Section: Generate Procurement Plan
                st.subheader("Generate Procurement Plan")

                if st.button("Generate Procurement Plan"):
                    procurement_plan = generate_procurement_plan(
                        mps_df,
                        safety_stock_days=safety_stock_days,
                        months_ahead=12  # Define how many months ahead to plan
                    )

                    if not procurement_plan.empty:
                        st.write("### Procurement Plan")
                        st.dataframe(procurement_plan)

                        # Download button for procurement plan
                        procurement_plan_excel = to_excel(procurement_plan, sheet_name='Procurement_Plan')

                        st.download_button(
                            label="Download Procurement Plan as Excel",
                            data=procurement_plan_excel,
                            file_name='Procurement_Plan.xlsx',
                            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        )
                    else:
                        st.info("Procurement plan is empty. Please ensure MPS table is populated correctly.")

                # Section: Display MPS Table
                st.subheader("Current Master Procurement Schedule")

                if not mps_df.empty:
                    st.dataframe(mps_df)
                    # Download MPS table
                    mps_excel = to_excel(mps_df, sheet_name='MPS')
                    st.download_button(
                        label="Download MPS as Excel",
                        data=mps_excel,
                        file_name='MPS.xlsx',
                        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    )
            else:
                st.info("MPS table is currently empty. Use the 'Suggest and Add All High Velocity Products' button to populate the table.")

        else:
            st.warning("Please upload both 90-Day Sales and Inventory CSV files to proceed.")

# ------------------------------
# Run the Streamlit App
# ------------------------------
if __name__ == "__main__":
    main()
