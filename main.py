# main.py
import tkinter as tk
from gui_app import BestdoriApp


def main():
    root = tk.Tk()
    app = BestdoriApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
