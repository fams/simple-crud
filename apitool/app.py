from flask import Flask, request, jsonify
from pymongo import MongoClient, errors
from jsonschema import validate, ValidationError
import os
import json
from bson import ObjectId

app = Flask(__name__)


# Conectar ao MongoDB com o URI da variável de ambiente
mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
try:
    # 5 segundos para tentar conexão
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    client.server_info()  # Testa a conexão
except errors.ServerSelectionTimeoutError as err:
    print(f"Erro ao conectar ao MongoDB: {err}")
    exit(1)  # Encerra o programa caso o MongoDB não esteja disponível

db = client.my_database

# Carregar todos os esquemas JSON do diretório 'schemas/'
schemas = {}
schemas_dir = 'schemas'

for filename in os.listdir(schemas_dir):
    if filename.endswith('.json'):
        try:
            with open(os.path.join(schemas_dir, filename), 'r') as schema_file:
                definition = json.load(schema_file)
            collection = definition["collection_name"]
            schemas[collection] = definition["schema"]
        except (IOError, json.JSONDecodeError) as e:
            print(f"Erro ao carregar o arquivo json {filename}: {e}")
            exit(1)
        except KeyError as e:
            print(f"Erro ao carregar o esquema {filename}: {e}")
            exit(1)


def validate_json(data, schema):
    """
    Valida os dados recebidos com base no JSON Schema fornecido.
    """
    try:
        validate(instance=data, schema=schema)
        return True, None
    except ValidationError as e:
        return False, e.message


def objectid_validator(object_id):
    """
    Valida e converte o object_id para ObjectId do MongoDB.
    """
    try:
        return ObjectId(object_id)
    except (TypeError, ValueError):
        return None


@app.route('/<collection>', methods=['POST'])
def create_object(collection):
    """
    Cria um novo objeto na coleção especificada.
    """
    if collection not in schemas:
        return jsonify({"error": "Collection not found"}), 404

    data = request.json
    schema = schemas[collection]

    is_valid, error_message = validate_json(data, schema)
    if not is_valid:
        return jsonify({"error": error_message}), 400

    collection_db = db[collection]
    try:
        result = collection_db.insert_one(data)
    except errors.PyMongoError as e:
        return jsonify({"error": f"Database error: {str(e)}"}), 500

    return jsonify({"message": "Object created", "id": str(result.inserted_id)}), 201


@app.route('/<collection>/<object_id>', methods=['GET'])
def get_object(collection, object_id):
    """
    Obtém um objeto pelo ID na coleção especificada.
    """
    if collection not in schemas:
        return jsonify({"error": "Collection not found"}), 404

    collection_db = db[collection]
    obj_id = objectid_validator(object_id)
    if not obj_id:
        return jsonify({"error": "Invalid object ID"}), 400

    try:
        obj = collection_db.find_one({"_id": obj_id})
    except errors.PyMongoError as e:
        return jsonify({"error": f"Database error: {str(e)}"}), 500

    if not obj:
        return jsonify({"error": "Object not found"}), 404

    obj['_id'] = str(obj['_id'])
    return jsonify(obj)


@app.route('/<collection>/<object_id>', methods=['PUT'])
def update_object(collection, object_id):
    """
    Atualiza um objeto com base nos dados fornecidos na coleção especificada.
    """
    if collection not in schemas:
        return jsonify({"error": "Collection not found"}), 404

    data = request.json
    schema = schemas[collection]

    is_valid, error_message = validate_json(data, schema)
    if not is_valid:
        return jsonify({"error": error_message}), 400

    collection_db = db[collection]
    obj_id = objectid_validator(object_id)
    if not obj_id:
        return jsonify({"error": "Invalid object ID"}), 400

    try:
        result = collection_db.update_one({"_id": obj_id}, {"$set": data})
    except errors.PyMongoError as e:
        return jsonify({"error": f"Database error: {str(e)}"}), 500

    if result.matched_count == 0:
        return jsonify({"error": "Object not found"}), 404

    return jsonify({"message": "Object updated"})


@app.route('/<collection>/<object_id>', methods=['DELETE'])
def delete_object(collection, object_id):
    """
    Exclui um objeto pelo ID na coleção especificada.
    """
    if collection not in schemas:
        return jsonify({"error": "Collection not found"}), 404

    collection_db = db[collection]
    obj_id = objectid_validator(object_id)
    if not obj_id:
        return jsonify({"error": "Invalid object ID"}), 400

    try:
        result = collection_db.delete_one({"_id": obj_id})
    except errors.PyMongoError as e:
        return jsonify({"error": f"Database error: {str(e)}"}), 500

    if result.deleted_count == 0:
        return jsonify({"error": "Object not found"}), 404

    return jsonify({"message": "Object deleted"})


@app.route('/healthcheck', methods=['GET'])
def healthcheck():
    """
    Verifica o estado do banco de dados e da aplicação.
    Retorna 200 se tudo estiver funcionando corretamente.
    """
    try:
        # Testa a conexão com o MongoDB
        client.server_info()  # Isso levanta uma exceção se o banco estiver inacessível
        return jsonify({"status": "healthy"}), 200
    except errors.ServerSelectionTimeoutError:
        return jsonify({"status": "unhealthy", "error": "Cannot connect to MongoDB"}), 503


@app.route('/collections', methods=['GET'])
def get_collections():
    """
    Retorna uma lista de todas as coleções disponíveis.
    """
    available_collections = schemas.keys()
    created_collections = db.list_collection_names()
    collections = {
        "collections": [
            {"schema": schemas[collection], "name": collection, "created": collection in created_collections}
            for collection in available_collections
        ]
    }
    return jsonify(collections)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
