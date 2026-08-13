from gmssl import sm2
from fastapi import HTTPException
# 要加密的消息
message = b"Hello, SM2 Encryption!"


def sm2decrypt(encoded_data):
    try:
        private_key = '4d054fdb1f62ba22f28f90bb568eb0dcde55b4a1348f698d13c6e90a5766ce48'
        public_key = '0488f9d256a380240609a20c54168f108a9e98cadaf150e3d109046201f2ea5078366ce38a4ea0ca40f584ce19514206f801dc101095753a3ef359989db0b14442'
# sm2_crypt = sm2.CryptSM2(public_key=public_key, private_key=private_key,mode=1, asn1=True)
#
#
# sm2_encrypt_data = sm2_crypt.encrypt(message)
# sm2_decrypt_data = sm2_crypt.decrypt(sm2_encrypt_data)
# print("Encrypted Data (hex):", sm2_encrypt_data)
# print("Encrypted Data (hex):", sm2_decrypt_data)

        sm2_crypt = sm2.CryptSM2(public_key=public_key, private_key=private_key, mode=1, asn1=True)
# encoded_data ='b3603bad0f9221e59a70e6de989c0ffe1f0535b831e11d969a380e9426f906e0c994e2dc315b11631092dde0ef623d63159af85c13f3881a71d87f06732e04d4e3de47d39c80d9cde5c4a5d5dd799c02bf5cea6d205906e67c1e066fb9108787c276c5d1951c9c84'
# # 要加密的数据
# plaintext = b"Hello, World!"
#
# # 使用公钥对数据进行加密
# ciphertext = sm2_crypt.encrypt(plaintext)

        a=bytes.fromhex(encoded_data)
# 使用私钥对数据进行解密
        decrypted_text = sm2_crypt.decrypt(a)

        password = decrypted_text.decode()
        return password
# # 打印加密和解密结果
# print("加密后的数据：",a)
# print("加密后的数据：", ciphertext.hex())
# print("解密后的数据：", decrypted_text.decode())
    except Exception as e:
        detail = f"密码非加密"
    # 返回HTTP错误响应
    raise HTTPException(status_code=400, detail=detail)