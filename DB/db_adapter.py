# IMPORTS
import sqlite3
import pandas

# CONSTANTS
APOINTMENT_DB = "appointments.db"
CUSTOMERS_DB  = "customers.db"
LEADS_DB      = "leads.db"
RECIPTS_DB    = "recipts.db"

# CLASSES
class Database:
    def __init__(self) -> None:
        self.appointments_conn = sqlite3.connect(APOINTMENT_DB)
        self.customers_conn = sqlite3.connect(CUSTOMERS_DB)
        self.leads_conn = sqlite3.connect(LEADS_DB)
        self.recipts_conn = sqlite3.connect(RECIPTS_DB)


# Handle 100% of the database procedures through this class and its functions.
    

