import logging
import uuid
from typing import Dict, List, Optional, Any
from datetime import datetime
from azure.cosmos import CosmosClient, PartitionKey, exceptions
from azure.cosmos.container import ContainerProxy
from azure.cosmos.database import DatabaseProxy
from azure.identity import DefaultAzureCredential, CredentialUnavailableError
from azure.cosmos.exceptions import CosmosHttpResponseError
from backend.core.config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Custom exception for database errors"""

    pass


class CosmosDBService:
    """Service for handling Azure Cosmos DB operations for metadata storage"""

    def __init__(self):
        """Initialize Azure Cosmos DB client"""
        self.logger = logger
        self.endpoint = settings.AZURE_COSMOS_DB_ENDPOINT
        self.key = settings.AZURE_COSMOS_DB_KEY
        self.database_id = settings.AZURE_COSMOS_DB_ID
        self.container_id = settings.AZURE_COSMOS_CONTAINER_ID

        # Use API key authentication when key is provided
        if self.key and not settings.USE_MANAGED_IDENTITY:
            # Use API key for authentication (master key auth)
            self.client = CosmosClient(
                self.endpoint,
                self.key
            )
            self.logger.info("Cosmos DB client initialized with API key")
        else:
            # Use DefaultAzureCredential for managed identity scenarios
            try:
                credential = DefaultAzureCredential(logging_enable=True)
                self.logger.info("Using DefaultAzureCredential for authentication")
                
                self.client = CosmosClient(
                    url=self.endpoint, credential=credential
                )
                self.logger.info("Cosmos DB client initialized with AAD authentication")
            except CredentialUnavailableError as e:
                self.logger.error(f"Credential unavailable: {str(e)}")
                raise DatabaseError(
                    "Failed to authenticate with Azure: Credential unavailable."
                )
            except Exception as e:
                self.logger.error(f"Unexpected error during authentication: {str(e)}")
                raise DatabaseError(f"Authentication error: {str(e)}")
        # Get or create database and container
        self.database = self._get_or_create_database()
        self.container = self._get_or_create_container()

        logger.info(
            f"Initialized Cosmos DB service - Database: {self.database_id}, Container: {self.container_id}"
        )

    def _get_or_create_database(self) -> DatabaseProxy:
        """Get or create the database"""
        try:
            return self.client.create_database_if_not_exists(id=self.database_id)
        except exceptions.CosmosHttpResponseError as e:
            logger.error(f"Failed to create/get database: {e}")
            raise

    def _get_or_create_container(self) -> ContainerProxy:
        """Get or create the container with appropriate partition key"""
        try:
            # Use media_type as partition key for good distribution
            partition_key = PartitionKey(path="/media_type")
            return self.database.create_container_if_not_exists(
                id=self.container_id,
                partition_key=partition_key,
                offer_throughput=400,  # Minimum throughput
            )
        except exceptions.CosmosHttpResponseError as e:
            logger.error(f"Failed to create/get container: {e}")
            raise

    def health_check(self) -> Dict[str, Any]:
        """Perform a health check on the Cosmos DB connection"""
        try:
            # Simple query to test connectivity and permissions
            query = "SELECT VALUE COUNT(1) FROM c WHERE c.doc_type = 'asset_metadata'"
            list(
                self.container.query_items(
                    query=query, enable_cross_partition_query=True
                )
            )

            return {
                "status": "healthy",
                "endpoint": self.endpoint,
                "database": self.database_id,
                "container": self.container_id,
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "endpoint": self.endpoint,
                "database": self.database_id,
                "container": self.container_id,
                "timestamp": datetime.utcnow().isoformat(),
            }

    def create_asset_metadata(self, asset_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create metadata record for an asset

        Args:
            asset_data: Dictionary containing asset information

        Returns:
            Created document with Cosmos DB metadata
        """
        try:
            # Generate unique ID if not provided
            if "id" not in asset_data:
                asset_data["id"] = str(uuid.uuid4())

            # Add timestamps
            current_time = datetime.utcnow().isoformat()
            asset_data["created_at"] = current_time
            asset_data["updated_at"] = current_time

            # Ensure media_type is set (required for partition key)
            if "media_type" not in asset_data:
                asset_data["media_type"] = "unknown"

            # Add document type for easier querying
            asset_data["doc_type"] = "asset_metadata"

            # Create the document
            created_item = self.container.create_item(body=asset_data)
            logger.info(f"Created metadata record for asset: {asset_data['id']}")

            return created_item

        except exceptions.CosmosHttpResponseError as e:
            logger.error(f"Failed to create asset metadata: {e}")
            raise

    def get_asset_metadata(
        self, asset_id: str, media_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get metadata for a specific asset

        Args:
            asset_id: Unique identifier for the asset
            media_type: Media type (used as partition key)

        Returns:
            Asset metadata dictionary or None if not found
        """
        try:
            item = self.container.read_item(item=asset_id, partition_key=media_type)
            return item
        except exceptions.CosmosResourceNotFoundError:
            logger.warning(f"Asset metadata not found: {asset_id}")
            return None
        except exceptions.CosmosHttpResponseError as e:
            logger.error(f"Failed to get asset metadata: {e}")
            raise

    def update_asset_metadata(
        self, asset_id: str, media_type: str, updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update metadata for an existing asset

        Args:
            asset_id: Unique identifier for the asset
            media_type: Media type (used as partition key)
            updates: Dictionary of fields to update

        Returns:
            Updated document
        """
        try:
            # Get existing item
            existing_item = self.get_asset_metadata(asset_id, media_type)
            if not existing_item:
                raise ValueError(f"Asset metadata not found: {asset_id}")

            # Update fields
            existing_item.update(updates)
            existing_item["updated_at"] = datetime.utcnow().isoformat()

            # Replace the item
            updated_item = self.container.replace_item(
                item=asset_id, body=existing_item
            )
            logger.info(f"Updated metadata for asset: {asset_id}")

            return updated_item

        except exceptions.CosmosHttpResponseError as e:
            logger.error(f"Failed to update asset metadata: {e}")
            raise

    def delete_asset_metadata(self, asset_id: str, media_type: str) -> bool:
        """
        Delete metadata for an asset

        Args:
            asset_id: Unique identifier for the asset
            media_type: Media type (used as partition key)

        Returns:
            True if deleted successfully, False if not found
        """
        try:
            self.container.delete_item(item=asset_id, partition_key=media_type)
            logger.info(f"Deleted metadata for asset: {asset_id}")
            return True
        except exceptions.CosmosResourceNotFoundError:
            logger.warning(f"Asset metadata not found for deletion: {asset_id}")
            return False
        except exceptions.CosmosHttpResponseError as e:
            logger.error(f"Failed to delete asset metadata: {e}")
            raise

    def query_assets(
        self,
        media_type: Optional[str] = None,
        folder_path: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0,
        order_by: str = "created_at",
        order_desc: bool = True,
    ) -> Dict[str, Any]:
        """
        Query assets with various filters

        Args:
            media_type: Filter by media type
            folder_path: Filter by folder path
            tags: Filter by tags (any of the provided tags)
            limit: Maximum number of results to return
            offset: Number of results to skip
            order_by: Field to order by
            order_desc: Whether to order in descending order

        Returns:
            Dictionary with items and pagination info
        """
        try:
            # Build query
            where_conditions = ["c.doc_type = 'asset_metadata'"]

            if media_type:
                where_conditions.append(f"c.media_type = '{media_type}'")

            if folder_path:
                where_conditions.append(f"c.folder_path = '{folder_path}'")

            if tags:
                # Check if any of the provided tags exist in the asset's tags array
                tag_conditions = [f"ARRAY_CONTAINS(c.tags, '{tag}')" for tag in tags]
                where_conditions.append(f"({' OR '.join(tag_conditions)})")

            where_clause = " AND ".join(where_conditions)
            order_direction = "DESC" if order_desc else "ASC"

            query = f"""
            SELECT * FROM c 
            WHERE {where_clause}
            ORDER BY c.{order_by} {order_direction}
            OFFSET {offset} LIMIT {limit}
            """

            # Execute query
            items = list(
                self.container.query_items(
                    query=query, enable_cross_partition_query=True
                )
            )

            # Get total count (separate query for performance)
            count_query = f"SELECT VALUE COUNT(1) FROM c WHERE {where_clause}"
            total_count = list(
                self.container.query_items(
                    query=count_query, enable_cross_partition_query=True
                )
            )[0]

            return {
                "items": items,
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": (offset + len(items)) < total_count,
            }

        except exceptions.CosmosHttpResponseError as e:
            logger.error(f"Failed to query assets: {e}")
            raise

    def search_assets(
        self, search_term: str, media_type: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Search assets by text in prompt, filename, tags, or other text fields

        Args:
            search_term: Text to search for
            media_type: Optional media type filter
            limit: Maximum number of results

        Returns:
            List of matching assets
        """
        try:
            # Build search conditions
            search_conditions = [
                f"CONTAINS(LOWER(c.prompt), LOWER('{search_term}'))",
                f"CONTAINS(LOWER(c.filename), LOWER('{search_term}'))",
                f"CONTAINS(LOWER(c.blob_name), LOWER('{search_term}'))",
                f"CONTAINS(LOWER(c.summary), LOWER('{search_term}'))",
                f"CONTAINS(LOWER(c.description), LOWER('{search_term}'))",
            ]

            where_conditions = [
                "c.doc_type = 'asset_metadata'",
                f"({' OR '.join(search_conditions)})",
            ]

            if media_type:
                where_conditions.append(f"c.media_type = '{media_type}'")

            where_clause = " AND ".join(where_conditions)

            query = f"""
            SELECT * FROM c 
            WHERE {where_clause}
            ORDER BY c.created_at DESC
            OFFSET 0 LIMIT {limit}
            """

            items = list(
                self.container.query_items(
                    query=query, enable_cross_partition_query=True
                )
            )

            logger.info(f"Search for '{search_term}' returned {len(items)} results")
            return items

        except exceptions.CosmosHttpResponseError as e:
            logger.error(f"Failed to search assets: {e}")
            raise

    def get_folder_stats(self, media_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Get statistics about folder usage

        Args:
            media_type: Optional media type filter

        Returns:
            Dictionary with folder statistics
        """
        try:
            where_conditions = ["c.doc_type = 'asset_metadata'"]

            if media_type:
                where_conditions.append(f"c.media_type = '{media_type}'")

            where_clause = " AND ".join(where_conditions)

            # Simple query to get all documents with their folder paths
            query = f"""
            SELECT c.folder_path
            FROM c 
            WHERE {where_clause} AND c.folder_path != null AND c.folder_path != ""
            """

            items = list(
                self.container.query_items(
                    query=query, enable_cross_partition_query=True
                )
            )

            # Count folders manually (since GROUP BY has issues)
            folder_counts = {}
            for item in items:
                folder_path = item.get("folder_path", "")
                if folder_path:
                    folder_counts[folder_path] = folder_counts.get(folder_path, 0) + 1

            # Convert to the expected format
            folder_stats = [
                {"folder_path": folder, "count": count}
                for folder, count in folder_counts.items()
            ]
            
            # Sort by count descending
            folder_stats.sort(key=lambda x: x["count"], reverse=True)

            return {"folder_stats": folder_stats, "total_folders": len(folder_stats)}

        except exceptions.CosmosHttpResponseError as e:
            logger.error(f"Failed to get folder stats: {e}")
            raise

    def get_recent_assets(
        self, media_type: Optional[str] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Get recently created assets

        Args:
            media_type: Optional media type filter
            limit: Maximum number of results

        Returns:
            List of recent assets
        """
        try:
            where_conditions = ["c.doc_type = 'asset_metadata'"]

            if media_type:
                where_conditions.append(f"c.media_type = '{media_type}'")

            where_clause = " AND ".join(where_conditions)

            query = f"""
            SELECT * FROM c 
            WHERE {where_clause}
            ORDER BY c.created_at DESC
            OFFSET 0 LIMIT {limit}
            """

            items = list(
                self.container.query_items(
                    query=query, enable_cross_partition_query=True
                )
            )

            return items

        except exceptions.CosmosHttpResponseError as e:
            logger.error(f"Failed to get recent assets: {e}")
            raise

    def batch_create_metadata(
        self, assets_data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Create multiple asset metadata records in batch

        Args:
            assets_data: List of asset data dictionaries

        Returns:
            List of created documents
        """
        created_items = []

        for asset_data in assets_data:
            try:
                created_item = self.create_asset_metadata(asset_data)
                created_items.append(created_item)
            except Exception as e:
                logger.error(f"Failed to create metadata for asset in batch: {e}")
                # Continue with other items
                continue

        logger.info(
            f"Batch created {len(created_items)} out of {len(assets_data)} metadata records"
        )
        return created_items
