#!/usr/bin/env python3
"""
Data Migration Script for LDA Group Time Tracking Application
Exports data from local MongoDB and imports to MongoDB Atlas
"""

import os
import json
from pymongo import MongoClient
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def connect_to_databases():
    """Connect to both source and destination databases"""
    # Source database (local)
    source_client = MongoClient("mongodb://localhost:27017")
    source_db = source_client["test_database"]
    
    # Destination database (MongoDB Atlas)
    dest_client = MongoClient("mongodb+srv://dukemcintyredm:wanxszN3gukWLU61@ldagroup.yhjwyg7.mongodb.net/?retryWrites=true&w=majority&appName=ldagroup")
    dest_db = dest_client["lda_timetracking"]
    
    return source_db, dest_db, source_client, dest_client

def export_collection_data(collection):
    """Export all data from a collection"""
    try:
        data = list(collection.find({}))
        logger.info(f"Exported {len(data)} documents from {collection.name}")
        return data
    except Exception as e:
        logger.error(f"Error exporting from {collection.name}: {e}")
        return []

def import_collection_data(collection, data):
    """Import data to a collection"""
    if not data:
        logger.info(f"No data to import for {collection.name}")
        return
    
    try:
        # Clear existing data
        collection.delete_many({})
        logger.info(f"Cleared existing data from {collection.name}")
        
        # Insert new data
        result = collection.insert_many(data)
        logger.info(f"Imported {len(result.inserted_ids)} documents to {collection.name}")
    except Exception as e:
        logger.error(f"Error importing to {collection.name}: {e}")

def migrate_data():
    """Main migration function"""
    logger.info("Starting data migration...")
    
    try:
        # Connect to databases
        source_db, dest_db, source_client, dest_client = connect_to_databases()
        
        # Test connections
        logger.info("Testing database connections...")
        source_db.admin.command('ping')
        dest_db.admin.command('ping')
        logger.info("✅ Both database connections successful")
        
        # Collections to migrate
        collections = ['workers', 'jobs', 'time_entries', 'materials']
        
        for collection_name in collections:
            logger.info(f"\nMigrating {collection_name}...")
            
            # Export from source
            source_collection = source_db[collection_name]
            data = export_collection_data(source_collection)
            
            # Import to destination
            dest_collection = dest_db[collection_name]
            import_collection_data(dest_collection, data)
        
        logger.info("\n✅ Data migration completed successfully!")
        
        # Display summary
        logger.info("\nMigration Summary:")
        for collection_name in collections:
            dest_count = dest_db[collection_name].count_documents({})
            logger.info(f"  {collection_name}: {dest_count} documents")
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
    finally:
        # Close connections
        source_client.close()
        dest_client.close()
        logger.info("Database connections closed")

def backup_current_data():
    """Create a backup of current data before migration"""
    logger.info("Creating backup of current data...")
    
    try:
        source_client = MongoClient("mongodb://localhost:27017")
        source_db = source_client["test_database"]
        
        collections = ['workers', 'jobs', 'time_entries', 'materials']
        backup_data = {}
        
        for collection_name in collections:
            collection = source_db[collection_name]
            data = list(collection.find({}))
            
            # Convert ObjectId and datetime to string for JSON serialization
            for doc in data:
                for key, value in doc.items():
                    if hasattr(value, 'isoformat'):  # datetime
                        doc[key] = value.isoformat()
            
            backup_data[collection_name] = data
        
        # Save backup to file
        backup_filename = f"lda_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(f"/app/{backup_filename}", 'w') as f:
            json.dump(backup_data, f, indent=2, default=str)
        
        logger.info(f"✅ Backup saved to {backup_filename}")
        source_client.close()
        
    except Exception as e:
        logger.error(f"Backup failed: {e}")

if __name__ == "__main__":
    print("LDA Group Time Tracking - Data Migration")
    print("="*50)
    
    # Create backup first
    backup_current_data()
    
    # Perform migration
    migrate_data()
    
    print("\nMigration process completed!")
    print("Next steps:")
    print("1. Restart the backend server")
    print("2. Test the application with the new database")
    print("3. Verify all data is present and functioning correctly")