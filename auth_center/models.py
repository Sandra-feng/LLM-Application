import bcrypt
from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/')
# client = MongoClient('mongodb://10.8.21.164:27017/')
db = client['auth_db']

# Define the user info collection
user_info_collection = db['user_info']


# Define functions to interact with the user info collection
def find_user_by_account(account):
    return user_info_collection.find_one({"account": account})


def insert_new_user_info(account, password):
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), salt)
    document = {'account': account, "password": hashed_password.decode('utf-8')}
    # print(document)
    user_info_collection.insert_one(document)


if __name__ == "__main__":
    insert_new_user_info("admin", "adminpwd")
    user_info = find_user_by_account("admin")
    print(user_info)
    print(bcrypt.checkpw('adminpwd'.encode('utf-8'), user_info['password'].encode('utf-8')))
