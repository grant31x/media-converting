import customtkinter as ctk
from tkinter import messagebox
import os

# Define and prepare app data directory
APP_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(APP_DATA_DIR, exist_ok=True)
import json
from notion_client import Client
from datetime import datetime

ctk.set_appearance_mode("dark")  # Options: "System" (default), "Dark", "Light"
ctk.set_default_color_theme("blue")  # Options: "blue" (default), "green", "dark-blue"


custom_emojis = {}

# Notion credentials
notion = Client(auth="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")
database_id = "1467a9c626d881c9932bca16df10b278"
def push_to_notion(income, tithing, savings, expenses, allocations, status_label=None):
    synced_any = False
    try:
        for category, amount in allocations.items():
            # Check if the category already exists in the database
            response = notion.databases.query(
                database_id=database_id,
                filter={
                    "property": "Expense",
                    "title": {
                        "equals": category
                    }
                }
            )

            if response["results"]:
                # Update the existing page only if amount changed by more than 0.01
                page_id = response["results"][0]["id"]
                existing_amount = response["results"][0]["properties"]["Amount"]["number"]
                new_amount = round(amount, 2)

                if abs(existing_amount - new_amount) > 0.01:
                    notion.pages.update(
                        page_id=page_id,
                        properties={
                            "Amount": {"number": new_amount}
                        }
                    )
                    synced_any = True
            else:
                # Create a new page
                notion.pages.create(
                    parent={"database_id": database_id},
                    properties={
                        "Expense": {
                            "title": [
                                {
                                    "text": {
                                        "content": category
                                    }
                                }
                            ]
                        },
                        "Amount": {
                            "number": round(amount, 2)
                        }
                    }
                )
                synced_any = True
        if status_label and synced_any:
            status_label.configure(text="✅ Synced to Notion", text_color="green")
            status_label.after(3000, lambda: status_label.configure(text=""))
        elif status_label:
            status_label.configure(text="✅ No changes to sync", text_color="gray")
            status_label.after(3000, lambda: status_label.configure(text=""))
    except Exception as e:
        print(f"Failed to sync to Notion: {e}")
        if status_label:
            status_label.configure(text="❌ Notion sync failed", text_color="red")
            status_label.after(5000, lambda: status_label.configure(text=""))

# Salary to Net Pay mapping (biweekly net pay)
salary_to_net = {
    66000: 2102.10,
    70000: 2230.65,  # This is correct biweekly value
    75000: 2389.69,
    80000: 2548.73,
    85000: 2707.76,
    90000: 2866.80,
    95000: 3025.84,
    100000: 3184.88
}

# Estimate net biweekly income for any salary in [60000, 300000]
def estimate_net_biweekly(salary):
    # Approximate formula based on the trend in the table
    # Adjusted slope based on net percentage trend ~79%
    return (salary / 26) * 0.79

def load_window_geometry():
    if os.path.exists(os.path.join(APP_DATA_DIR, "window_size.txt")):
        with open(os.path.join(APP_DATA_DIR, "window_size.txt"), "r") as file:
            return file.read().strip()
    return "450x700"

def save_window_geometry():
    with open(os.path.join(APP_DATA_DIR, "window_size.txt"), "w") as file:
        geom = root.geometry()
        file.write(geom)

# Persistent static expenses dictionary
static_expense_file = os.path.join(APP_DATA_DIR, "static_expenses.json")
if os.path.exists(static_expense_file):
    with open(static_expense_file, "r") as f:
        static_expenses = json.load(f)
else:
    static_expenses = {
        "Car Payment": 223.36,
        "Student Loan": 88.79,
        "T-Mobile": 63.50,
        "Car Insurance": 57.30,
        "Gym": 14.50,
        "Car Wash": 12.00,
        "ChatGPT": 10.72,
        "Prime": 8.04,
        "Spotify": 6.43,
        "iCloud": 3.50
    }

def load_income():
    if os.path.exists(os.path.join(APP_DATA_DIR, "income.txt")):
        with open(os.path.join(APP_DATA_DIR, "income.txt"), "r") as file:
            try:
                return float(file.read())
            except ValueError:
                return 2000.0
    return 2000.0

# Persistent storage for "What if income"
def load_alt_income():
    if os.path.exists(os.path.join(APP_DATA_DIR, "alt_income.txt")):
        with open(os.path.join(APP_DATA_DIR, "alt_income.txt"), "r") as file:
            try:
                return file.read().strip()
            except:
                return "70000"
    return "70000"

def save_alt_income(value):
    with open(os.path.join(APP_DATA_DIR, "alt_income.txt"), "w") as file:
        file.write(str(value))

def save_income(income):
    with open(os.path.join(APP_DATA_DIR, "income.txt"), "w") as file:
        file.write(str(income))

def format_currency(amount):
    return f"${amount:.2f}"

def calculate_budget(income, active_cash_override=None):
    tithing = income * 0.10
    active_cash = 400.0 if active_cash_override is None else active_cash_override
    total_static = sum(static_expenses.values())
    savings = max(income - (tithing + active_cash + total_static), 0.0)
    allocations = {
        "Savings": savings,
        "Active Cash": active_cash,
        "Tithing": tithing,
        **static_expenses
    }
    return allocations


# --- Static Editor Functionality ---
def open_static_editor():
    editor = ctk.CTkToplevel(root)
    editor.title("G's Money Tracker – Edit Static Amounts")

    editor_geometry_file = os.path.join(APP_DATA_DIR, "static_editor_geometry.txt")
    if os.path.exists(editor_geometry_file):
        with open(editor_geometry_file, "r") as f:
            editor.geometry(f.read().strip())
    else:
        editor.geometry("300x500")

    def save_editor_geometry():
        with open(editor_geometry_file, "w") as f:
            f.write(editor.geometry())

    def save_changes():
        global calculate_budget
        try:
            updated_static = {key: float(entries[key].get()) for key in static_expenses}
            updated_active_cash = float(entries.pop("Active Cash").get())
            new_total_static = sum(updated_static.values())
            income = float(income_entry.get())
            tithing = income * 0.10

            previous_allocations = calculate_budget(income)
            original_active_cash = previous_allocations["Active Cash"]
            original_savings = previous_allocations["Savings"]

            savings = income - (tithing + updated_active_cash + new_total_static)

            if savings < 0:
                messagebox.showerror("Allocation Error", "Savings would go below 0 with this active cash setting.")
                return

            # Save the updated values as per new requirements
            save_income(income)
            static_expenses.update(updated_static)
            # Persist static_expenses to file
            with open(static_expense_file, "w") as f:
                json.dump(static_expenses, f)
            # Save updated_active_cash as a new global value by writing to a file
            with open(os.path.join(APP_DATA_DIR, "active_cash.txt"), "w") as f:
                f.write(str(updated_active_cash))
            def calculate_budget(income, active_cash_override=None):
                tithing = income * 0.10
                active_cash = updated_active_cash if active_cash_override is None else active_cash_override
                total_static = sum(static_expenses.values())
                savings = max(income - (tithing + active_cash + total_static), 0.0)
                return {
                    "Savings": savings,
                    "Active Cash": active_cash,
                    "Tithing": tithing,
                    **static_expenses
                }
            custom_emojis["Active Cash"] = "💳"
            save_editor_geometry()
            editor.destroy()
            update_display()

        except ValueError:
            messagebox.showwarning("Invalid Input", "Please enter valid numbers for all fields.")

    ctk.CTkLabel(editor, text="Update Static Expenses", font=("Helvetica", 14, "bold")).pack(pady=10, padx=10)

    def refresh_editor():
        editor.destroy()
        open_static_editor()

    entries = {}
    for key in static_expenses:
        frame = ctk.CTkFrame(editor)
        frame.pack(pady=5, padx=10, fill="x")

        def delete_category(category=key):
            if category in static_expenses:
                del static_expenses[category]
                save_editor_geometry()
                editor.update()
                refresh_editor()

        delete_btn = ctk.CTkButton(frame, text="🗑", width=24, height=24, fg_color="red", text_color="white",
                                   command=delete_category)
        delete_btn.pack(side="left", padx=(0, 5))

        ctk.CTkLabel(frame, text=key, width=150, anchor="w").pack(side="left", padx=(0, 10))
        entry = ctk.CTkEntry(frame, width=100, height=30)
        entry.insert(0, f"{static_expenses[key]:.2f}")
        entry.pack(side="right")
        entries[key] = entry

    # Add editable Active Cash field
    frame = ctk.CTkFrame(editor)
    frame.pack(pady=5, padx=10, fill="x")

    ctk.CTkLabel(frame, text="Active Cash", width=150, anchor="w").pack(side="left", padx=(0, 10))
    active_cash_entry = ctk.CTkEntry(frame, width=100, height=30)
    active_cash_entry.insert(0, f"{calculate_budget(load_income())['Active Cash']:.2f}")
    active_cash_entry.pack(side="right")
    entries["Active Cash"] = active_cash_entry

    # Add new static category section
    ctk.CTkLabel(editor, text="Add New Static Expense", font=("Helvetica", 12, "bold")).pack(pady=(20, 5))

    new_name_entry = ctk.CTkEntry(editor, placeholder_text="Name (e.g. ☕ Coffee)", height=35)
    new_name_entry.pack(pady=2, padx=10, fill="x")

    new_amount_entry = ctk.CTkEntry(editor, placeholder_text="Amount (e.g. 15.00)", height=35)
    new_amount_entry.pack(pady=2, padx=10, fill="x")

    new_emoji_entry = ctk.CTkEntry(editor, placeholder_text="Emoji (optional)", height=35)
    new_emoji_entry.pack(pady=2, padx=10, fill="x")

    def add_new_category():
        name = new_name_entry.get().strip()
        try:
            amount = float(new_amount_entry.get().strip())
        except ValueError:
            messagebox.showwarning("Invalid Input", "Please enter a valid amount.")
            return

        emoji = new_emoji_entry.get().strip()

        if not name:
            messagebox.showwarning("Invalid Input", "Name cannot be empty.")
            return
        if name in static_expenses:
            messagebox.showwarning("Duplicate Entry", "This category already exists.")
            return

        test_expenses = static_expenses.copy()
        test_expenses[name] = amount
        income = load_income()
        tithing = income * 0.10
        total_static = sum(test_expenses.values())
        remaining = income - (tithing + total_static)
        active_cash = remaining if remaining >= 400 else remaining
        if active_cash < 0:
            messagebox.showerror("Allocation Error", "Active Cash would go below 0 with this addition.")
            return

        static_expenses[name] = amount
        # Persist static_expenses to file after addition
        with open(static_expense_file, "w") as f:
            json.dump(static_expenses, f)
        if emoji:
            custom_emojis[name] = emoji
        save_editor_geometry()
        editor.destroy()
        update_display()

    ctk.CTkButton(editor, text="Add Category", command=add_new_category).pack(pady=5)

    ctk.CTkButton(editor, text="Save", command=save_changes).pack(pady=15, padx=10)

def animate_resize(target_width, target_height, duration=300):
    steps = 30
    delay = duration // steps

    current_width = root.winfo_width()
    current_height = root.winfo_height()
    width_delta = (target_width - current_width) / steps
    height_delta = (target_height - current_height) / steps

    def step(i=0):
        if i > steps:
            return
        new_width = int(current_width + width_delta * i)
        new_height = int(current_height + height_delta * i)
        root.geometry(f"{new_width}x{new_height}")
        root.update_idletasks()
        root.after(delay, lambda: step(i + 1))

    step()

def update_display(sync_to_notion=True):
    try:
        income_str = income_entry.get().strip()
        if not income_str.replace('.', '', 1).isdigit():
            raise ValueError("Invalid numeric input.")
        income = float(income_str)
        save_income(income)
        allocations = calculate_budget(income)

        alt_income_str = income_alt_entry.get().strip().replace(",", "")
        save_alt_income(alt_income_str)
        # Accept both integer and float values for alt_income_str
        if alt_income_str.replace('.', '', 1).isdigit():
            salary_val = float(alt_income_str)
            if salary_val in salary_to_net:
                biweekly_net = salary_to_net[salary_val]
            elif 60000 <= salary_val <= 300000:
                biweekly_net = estimate_net_biweekly(salary_val)
            else:
                biweekly_net = salary_val
            alt_income = round(biweekly_net, 2)
        else:
            alt_income = income

        alt_allocations = calculate_budget(alt_income)

        output_text = f"\n💰 Budget Breakdown for {format_currency(income)}\n"
        output_text += "=" * 42 + "\n"
        output_text += f"\n{'Category':<22}{'Amount':>10}  {'%':>6}\n"
        output_text += f"{'-'*42}\n"
        emojis = {
            "Savings": "💰", "Active Cash": "💳", "Tithing": "🙏",
            "Car Payment": "🚗", "Student Loan": "🎓", "T-Mobile": "📱",
            "Car Insurance": "🛡️", "Gym": "🏋️", "Car Wash": "🧼",
            "ChatGPT": "🤖", "Prime": "📦", "Spotify": "🎵", "iCloud": "☁️"
        }
        emojis.update(custom_emojis)
        for category, amount in allocations.items():
            percent = (amount / income) * 100
            percent_str = f"{percent:.1f}%"
            emoji = emojis.get(category, "")
            output_text += f"{emoji} {category:<20}{format_currency(amount):>10}  {percent_str:>6}\n"

        # Add summary totals below the allocation table
        static_total = sum(amount for category, amount in allocations.items() if category not in ["Savings", "Active Cash", "Tithing"])

        monthly_static_total = static_total * 2
        monthly_allocated = sum(allocations.values()) * 2
        monthly_leftover = (income - sum(allocations.values())) * 2

        output_text += f"\n\n📦 Static Summary\n"
        output_text += "=" * 42 + "\n"
        output_text += f"{'Static Expenses Total:':<28}{format_currency(static_total)}\n"

        output_text += f"\n📊 Monthly Summary\n"
        output_text += "=" * 42 + "\n"
        output_text += f"{'Static Expenses Total:':<28}{format_currency(monthly_static_total)}\n"
        output_text += f"{'Total Monthly Income:':<28}{format_currency(monthly_allocated)}\n"
        output_text += f"{'Total Monthly Savings:':<28}{format_currency(allocations['Savings'] * 2)}\n"

        output_text += f"\n🧪 Alternative Income Scenario: {format_currency(alt_income * 2)}\n"
        output_text += "=" * 42 + "\n"
        alt_savings = alt_allocations["Savings"]
        alt_tithing = alt_allocations["Tithing"]
        base_savings = allocations.get("Savings", 0)
        base_tithing = allocations.get("Tithing", 0)
        delta_savings = alt_savings - base_savings
        delta_tithing = alt_tithing - base_tithing

        result_label.delete(1.0, tk.END)
        lines = output_text.splitlines()
        for i, line in enumerate(lines):
            if "Savings" in line and "Monthly" not in line:
                result_label.insert(tk.END, line + "\n", "savings")
            elif "Total Monthly Savings" in line:
                result_label.insert(tk.END, line + "\n", "savings")
            else:
                result_label.insert(tk.END, line + "\n")

            # Add slight spacing only after category rows (not headers or summaries)
            if i > 2 and lines[i-1] != "" and line.strip() != "" and not line.startswith("-"):
                result_label.insert(tk.END, "\n")

        # Render the alternative scenario output at the end, after delete
        if delta_savings > 0:
            result_label.insert(
                tk.END,
                f"{'Monthly Savings:':<28}{format_currency(alt_savings * 2)} (+{(delta_savings*2):.2f})\n",
                "savings"
            )
        else:
            result_label.insert(
                tk.END,
                f"{'Monthly Savings:':<28}{format_currency(alt_savings * 2)}\n",
                "savings"
            )

        if delta_tithing > 0:
            result_label.insert(
                tk.END,
                f"{'Tithing':<28}{format_currency(alt_tithing * 2)} (+{(delta_tithing*2):.2f})\n"
            )
        else:
            result_label.insert(
                tk.END,
                f"{'Tithing':<28}{format_currency(alt_tithing * 2)}\n"
            )

        result_label.pack(padx=10, pady=10, fill="both", expand=True)
        button_frame.pack(side="bottom", anchor="w", padx=10, pady=10)
        # Replace animate_resize with direct geometry set
        root.geometry(f"540x750")
    except ValueError:
        messagebox.showwarning("⚠️ Invalid Input", "Please enter a valid number.")
    if sync_to_notion:
        push_to_notion(
            income=income,
            tithing=allocations["Tithing"],
            savings=allocations["Savings"],
            expenses=sum(v for k, v in allocations.items() if k not in ["Savings", "Tithing", "Active Cash"]),
            allocations=allocations,
            status_label=notion_status_label
        )
    save_window_geometry()

# GUI setup
root = ctk.CTk()
root.title("G's Money Tracker")
import tkinter as tk  # for Text widget

# --- Modern main frame container ---
main_frame = ctk.CTkFrame(root, corner_radius=10)
main_frame.pack(pady=20, padx=20, fill="both", expand=True)

# --- Header ---
ctk.CTkLabel(main_frame, text="G Budget Tracker", font=("Helvetica", 22, "bold")).pack(pady=10)

# --- Horizontal input fields frame ---
input_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
input_frame.pack(pady=(5, 15))

# --- Income entry ---
income_entry = ctk.CTkEntry(main_frame, font=("Helvetica", 14), justify="center", width=200, height=35)
income_entry.insert(0, f"{load_income():.2f}")

income_alt_entry = ctk.CTkEntry(main_frame, font=("Helvetica", 12), justify="center", width=200, height=30)
income_alt_entry.insert(0, load_alt_income())

# Stack label and entry together in columns
income_column = ctk.CTkFrame(input_frame, fg_color="transparent")
alt_income_column = ctk.CTkFrame(input_frame, fg_color="transparent")
income_column.pack(side="left", padx=(0, 10))
alt_income_column.pack(side="left")

ctk.CTkLabel(income_column, text="Enter your income:", font=("Helvetica", 14, "bold")).pack(anchor="center", pady=(0, 4))
income_entry.pack(in_=income_column)

ctk.CTkLabel(alt_income_column, text="What if income was:", font=("Helvetica", 14, "bold")).pack(anchor="center", pady=(0, 4))
income_alt_entry.pack(in_=alt_income_column)

# --- Calculate Button full width ---
ctk.CTkButton(main_frame, text="Generate & Sync to Notion", font=("Helvetica", 14), command=update_display).pack(pady=10, padx=10, fill="x")
ctk.CTkButton(main_frame, text="Calculate Without API", font=("Helvetica", 14), command=lambda: update_display(sync_to_notion=False)).pack(pady=(0, 10), padx=10, fill="x")

# --- Styled Results Text ---
result_label = tk.Text(
    main_frame,
    font=("Courier", 16),
    bg="#1e1e1e",
    fg="white",
    wrap="none",
    height=20,
    width=60,
    bd=0,
    relief="flat",
    padx=12,
    pady=10
)
result_label.tag_configure("savings", foreground="lime")

# --- Bottom buttons inside main_frame ---
button_frame = ctk.CTkFrame(main_frame)

result_label.pack_forget()
button_frame.pack_forget()

ctk.CTkButton(button_frame, text="Edit Static Amounts", font=("Helvetica", 13), command=open_static_editor).pack(side="left", padx=(0, 10), pady=5)
ctk.CTkButton(button_frame, text="Quit", font=("Helvetica", 13), command=root.quit).pack(side="left", pady=5)

# --- Notion status label (sync results) ---
notion_status_label = ctk.CTkLabel(main_frame, text="", font=("Helvetica", 12))
notion_status_label.pack(pady=(0, 10))


# Ensure window size is saved on close and after any user-driven resize
def on_closing():
    root.update_idletasks()
    save_window_geometry()
    root.destroy()

root.geometry(load_window_geometry())
root.protocol("WM_DELETE_WINDOW", on_closing)

root.mainloop()