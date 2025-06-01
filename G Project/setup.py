from setuptools import setup

APP = ['Dashboard.py']
DATA_FILES = [
    ('', ['tools.py', 'moneytracker.py', 'cc_payments.py'])
]
OPTIONS = {
    'argv_emulation': True,
    'packages': ['PyQt5', 'tkinter', 'customtkinter'],
    'includes': ['tkinter', 'customtkinter'],
    'frameworks': [
        '/Library/Frameworks/Python.framework/Versions/3.11/lib/libtcl8.6.dylib',
        '/Library/Frameworks/Python.framework/Versions/3.11/lib/libtk8.6.dylib'
    ]
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)