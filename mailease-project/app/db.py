from pymongo import MongoClient

def get_db():
    client = MongoClient("mongodb://localhost:27017/")  # Connect to MongoDB (adjust URI as necessary)
    return client['mailease']  # Return the database instance
