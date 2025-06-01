import tkinter as tk

def calculate_total():
    try:
        values = [
            float(entry_wf_3282.get() or 0),
            float(entry_wf_8269.get() or 0),
            float(entry_sofi.get() or 0),
            float(entry_apple.get() or 0),
            float(entry_citi.get() or 0)
        ]
        total = sum(values)
        total_label.config(text=f"Total: ${total:,.2f}")
    except ValueError:
        total_label.config(text="Please enter valid numbers.")

# Create the main window
root = tk.Tk()
root.title("Account Totals")

# Labels and entry fields
tk.Label(root, text="WellsFargo 3282").grid(row=0, column=0, sticky="e")
entry_wf_3282 = tk.Entry(root)
entry_wf_3282.grid(row=0, column=1)

tk.Label(root, text="WellsFargo 8269").grid(row=1, column=0, sticky="e")
entry_wf_8269 = tk.Entry(root)
entry_wf_8269.grid(row=1, column=1)

tk.Label(root, text="SoFi").grid(row=2, column=0, sticky="e")
entry_sofi = tk.Entry(root)
entry_sofi.grid(row=2, column=1)

tk.Label(root, text="Apple Card").grid(row=3, column=0, sticky="e")
entry_apple = tk.Entry(root)
entry_apple.grid(row=3, column=1)

tk.Label(root, text="Citi Visa").grid(row=4, column=0, sticky="e")
entry_citi = tk.Entry(root)
entry_citi.grid(row=4, column=1)

# Button to calculate total
tk.Button(root, text="Calculate Total", command=calculate_total).grid(row=5, column=0, columnspan=2, pady=10)

# Label to display total
total_label = tk.Label(root, text="Total: $0.00", font=("Helvetica", 12, "bold"))
total_label.grid(row=6, column=0, columnspan=2)

root.mainloop()
