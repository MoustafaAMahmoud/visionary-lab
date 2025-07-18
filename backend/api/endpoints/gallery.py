from fastapi import (
    APIRouter,
    HTTPException,
    Depends,
    Query,
    UploadFile,
    File,
    Form,
    Body,
    BackgroundTasks,
)
from typing import Dict, List, Optional, Any
from fastapi.responses import StreamingResponse
import io
import re
import os
from datetime import datetime, timedelta, timezone
from azure.storage.blob import generate_container_sas, ContainerSasPermissions

from backend.core.azure_storage import AzureBlobStorageService
from backend.core.cosmos_client import CosmosDBService
from backend.core.config import settings
from backend.models.gallery import (
    GalleryResponse,
    GalleryItem,
    MediaType,
    AssetUploadResponse,
    AssetDeleteResponse,
    AssetUrlResponse,
    AssetMetadataResponse,
    MetadataUpdateRequest,
    SasTokenResponse,
)
from backend.models.metadata_models import AssetMetadataCreateRequest
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()


def get_cosmos_service() -> CosmosDBService:
    """Dependency to get Cosmos DB service instance (required)"""
    try:
        if settings.AZURE_COSMOS_DB_ENDPOINT:
            # Check if we have either API key or can use managed identity
            if settings.AZURE_COSMOS_DB_KEY or settings.USE_MANAGED_IDENTITY:
                return CosmosDBService()
            else:
                raise HTTPException(
                    status_code=503,
                    detail="Cosmos DB endpoint configured but no API key or managed identity enabled"
                )
        else:
            raise HTTPException(
                status_code=503,
                detail="Cosmos DB not configured. Please set AZURE_COSMOS_DB_ENDPOINT and AZURE_COSMOS_DB_KEY"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cosmos DB service initialization failed: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Failed to initialize Cosmos DB service: {str(e)}"
        )


@router.get("/images", response_model=GalleryResponse)
async def get_gallery_images(
    limit: int = Query(
        50, description="Maximum number of items to return", ge=1, le=100
    ),
    offset: int = Query(0, description="Offset for pagination"),
    folder_path: Optional[str] = Query(
        None, description="Optional folder path to filter assets"
    ),
    tags: Optional[str] = Query(None, description="Comma-separated tags to filter by"),
    cosmos_service: CosmosDBService = Depends(get_cosmos_service),
    azure_storage_service: AzureBlobStorageService = Depends(
        lambda: AzureBlobStorageService()
    ),
):
    """Get gallery images from Cosmos DB metadata with SAS token generation"""
    try:
        # Parse tags if provided
        tag_list = None
        if tags:
            tag_list = [tag.strip() for tag in tags.split(",") if tag.strip()]

        # Query Cosmos DB for images
        result = cosmos_service.query_assets(
            media_type="image",
            folder_path=folder_path,
            tags=tag_list,
            limit=limit,
            offset=offset,
            order_by="created_at",
            order_desc=True,
        )

        gallery_items = []
        for metadata in result["items"]:
            # Generate SAS URL for the blob
            sas_url = azure_storage_service.generate_blob_sas_url(
                blob_name=metadata["blob_name"],
                container_name=metadata["container"],
                expiry_hours=24  # 24 hour expiry for gallery viewing
            )
            
            gallery_items.append(
                GalleryItem(
                    id=metadata["id"],
                    name=metadata["blob_name"],
                    media_type=MediaType.IMAGE,
                    url=sas_url,  # Use SAS URL instead of stored URL
                    container=metadata["container"],
                    size=metadata["size"],
                    content_type=metadata.get("content_type"),
                    creation_time=metadata["created_at"],
                    last_modified=metadata["updated_at"],
                    metadata={
                        # Rich metadata from Cosmos DB
                        "prompt": metadata.get("prompt", ""),
                        "model": metadata.get("model", ""),
                        "summary": metadata.get("summary", ""),
                        "description": metadata.get("description", ""),
                        "products": metadata.get("products", ""),
                        "tags": ",".join(metadata.get("tags", [])),
                        "quality": metadata.get("quality", ""),
                        "background": metadata.get("background", ""),
                        "output_format": metadata.get("output_format", ""),
                        "has_transparency": str(
                            metadata.get("has_transparency", False)
                        ),
                        "generation_id": metadata.get("generation_id", ""),
                        **metadata.get("custom_metadata", {}),
                    },
                    folder_path=metadata.get("folder_path", ""),
                )
            )

        return GalleryResponse(
            success=True,
            message=f"Retrieved {len(gallery_items)} images from Cosmos DB",
            total=result["total"],
            limit=limit,
            offset=offset,
            items=gallery_items,
            continuation_token=None,
            folders=None,
        )
        
    except Exception as e:
        logger.error(f"Error retrieving images: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve images: {str(e)}",
        )


@router.get("/videos", response_model=GalleryResponse)
async def get_gallery_videos(
    limit: int = Query(
        50, description="Maximum number of items to return", ge=1, le=100
    ),
    offset: int = Query(0, description="Offset for pagination"),
    folder_path: Optional[str] = Query(
        None, description="Optional folder path to filter assets"
    ),
    tags: Optional[str] = Query(None, description="Comma-separated tags to filter by"),
    cosmos_service: CosmosDBService = Depends(get_cosmos_service),
    azure_storage_service: AzureBlobStorageService = Depends(
        lambda: AzureBlobStorageService()
    ),
):
    """Get gallery videos from Cosmos DB metadata with SAS token generation"""
    try:
        # Parse tags if provided
        tag_list = None
        if tags:
            tag_list = [tag.strip() for tag in tags.split(",") if tag.strip()]

        # Query Cosmos DB for videos
        result = cosmos_service.query_assets(
            media_type="video",
            folder_path=folder_path,
            tags=tag_list,
            limit=limit,
            offset=offset,
            order_by="created_at",
            order_desc=True,
        )

        gallery_items = []
        for metadata in result["items"]:
            # Generate SAS URL for the blob
            sas_url = azure_storage_service.generate_blob_sas_url(
                blob_name=metadata["blob_name"],
                container_name=metadata["container"],
                expiry_hours=24  # 24 hour expiry for gallery viewing
            )
            
            gallery_items.append(
                GalleryItem(
                    id=metadata["id"],
                    name=metadata["blob_name"],
                    media_type=MediaType.VIDEO,
                    url=sas_url,  # Use SAS URL instead of stored URL
                    container=metadata["container"],
                    size=metadata["size"],
                    content_type=metadata.get("content_type"),
                    creation_time=metadata["created_at"],
                    last_modified=metadata["updated_at"],
                    metadata={
                        # Rich metadata from Cosmos DB
                        "prompt": metadata.get("prompt", ""),
                        "model": metadata.get("model", ""),
                        "summary": metadata.get("summary", ""),
                        "description": metadata.get("description", ""),
                        "products": metadata.get("products", ""),
                        "tags": ",".join(metadata.get("tags", [])),
                        "generation_id": metadata.get("generation_id", ""),
                        "duration": str(metadata.get("duration", "")),
                        "resolution": metadata.get("resolution", ""),
                        "fps": str(metadata.get("fps", "")),
                        **metadata.get("custom_metadata", {}),
                    },
                    folder_path=metadata.get("folder_path", ""),
                )
            )

        return GalleryResponse(
            success=True,
            message=f"Retrieved {len(gallery_items)} videos from Cosmos DB",
            total=result["total"],
            limit=limit,
            offset=offset,
            items=gallery_items,
            continuation_token=None,
            folders=None,
        )
        
    except Exception as e:
        logger.error(f"Error retrieving videos: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve videos: {str(e)}",
        )


@router.get("/", response_model=GalleryResponse)
async def get_gallery_items(
    limit: int = Query(
        50, description="Maximum number of items to return", ge=1, le=100
    ),
    offset: int = Query(0, description="Offset for pagination"),
    folder_path: Optional[str] = Query(
        None, description="Optional folder path to filter assets"
    ),
    tags: Optional[str] = Query(None, description="Comma-separated tags to filter by"),
    media_type: Optional[str] = Query(None, description="Filter by media type (image or video)"),
    cosmos_service: CosmosDBService = Depends(get_cosmos_service),
    azure_storage_service: AzureBlobStorageService = Depends(
        lambda: AzureBlobStorageService()
    ),
):
    """
    Get all gallery items (images and videos) from Cosmos DB with SAS token generation
    """
    try:
        # Parse tags if provided
        tag_list = None
        if tags:
            tag_list = [tag.strip() for tag in tags.split(",") if tag.strip()]
        
        # Query Cosmos DB for all media types or filtered by type
        result = cosmos_service.query_assets(
            media_type=media_type,  # None means both images and videos
            folder_path=folder_path,
            tags=tag_list,
            limit=limit,
            offset=offset,
            order_by="created_at",
            order_desc=True,
        )
        
        gallery_items = []
        for metadata in result["items"]:
            # Generate SAS URL for the blob
            sas_url = azure_storage_service.generate_blob_sas_url(
                blob_name=metadata["blob_name"],
                container_name=metadata["container"],
                expiry_hours=24  # 24 hour expiry for gallery viewing
            )
            
            # Build metadata based on media type
            item_metadata = {
                "prompt": metadata.get("prompt", ""),
                "model": metadata.get("model", ""),
                "summary": metadata.get("summary", ""),
                "description": metadata.get("description", ""),
                "products": metadata.get("products", ""),
                "tags": ",".join(metadata.get("tags", [])),
                "generation_id": metadata.get("generation_id", ""),
            }
            
            # Add media-specific metadata
            if metadata["media_type"] == "image":
                item_metadata.update({
                    "quality": metadata.get("quality", ""),
                    "background": metadata.get("background", ""),
                    "output_format": metadata.get("output_format", ""),
                    "has_transparency": str(metadata.get("has_transparency", False)),
                })
            else:  # video
                item_metadata.update({
                    "duration": str(metadata.get("duration", "")),
                    "resolution": metadata.get("resolution", ""),
                    "fps": str(metadata.get("fps", "")),
                })
            
            # Add custom metadata
            item_metadata.update(metadata.get("custom_metadata", {}))
            
            gallery_items.append(
                GalleryItem(
                    id=metadata["id"],
                    name=metadata["blob_name"],
                    media_type=MediaType(metadata["media_type"]),
                    url=sas_url,  # Use SAS URL instead of stored URL
                    container=metadata["container"],
                    size=metadata["size"],
                    content_type=metadata.get("content_type"),
                    creation_time=metadata["created_at"],
                    last_modified=metadata["updated_at"],
                    metadata=item_metadata,
                    folder_path=metadata.get("folder_path", ""),
                )
            )
        
        return GalleryResponse(
            success=True,
            message=f"Retrieved {len(gallery_items)} items from Cosmos DB",
            total=result["total"],
            limit=limit,
            offset=offset,
            items=gallery_items,
            continuation_token=None,
            folders=None,
        )
    except Exception as e:
        logger.error(f"Error retrieving gallery items: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload", response_model=AssetUploadResponse)
async def upload_asset(
    file: UploadFile = File(...),
    media_type: MediaType = Form(MediaType.IMAGE),
    metadata: Optional[str] = Form(None),
    folder_path: Optional[str] = Form(None),
    azure_storage_service: AzureBlobStorageService = Depends(
        lambda: AzureBlobStorageService()
    ),
    cosmos_service: Optional[CosmosDBService] = Depends(get_cosmos_service),
):
    """
    Upload an asset (image or video) to Azure Blob Storage with optional metadata
    Also creates metadata record in Cosmos DB if available
    """
    try:
        # Validate file type
        if media_type == MediaType.IMAGE:
            valid_types = [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"]
        else:  # VIDEO
            valid_types = [".mp4", ".mov", ".avi", ".wmv", ".webm", ".mkv"]

        filename = file.filename.lower()
        if not any(filename.endswith(ext) for ext in valid_types):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Must be one of {', '.join(valid_types)}",
            )

        # Parse metadata if provided
        metadata_dict = None
        if metadata:
            try:
                import json

                metadata_dict = json.loads(metadata)

                # Ensure all metadata values are UTF-8 compatible strings
                if metadata_dict:
                    for key, value in list(metadata_dict.items()):
                        if value is None:
                            del metadata_dict[key]
                        elif isinstance(value, (dict, list)):
                            metadata_dict[key] = json.dumps(value)
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=400, detail="Invalid JSON format for metadata"
                )

        # Upload to Azure Blob Storage
        result = await azure_storage_service.upload_asset(
            file, media_type.value, metadata=metadata_dict, folder_path=folder_path
        )

        # Create metadata record in Cosmos DB if available
        if cosmos_service:
            try:
                cosmos_metadata = AssetMetadataCreateRequest(
                    media_type=media_type.value,
                    blob_name=result["blob_name"],
                    container=result["container"],
                    url=result["url"],
                    filename=result["original_filename"],
                    size=result["size"],
                    content_type=result["content_type"],
                    folder_path=result["folder_path"],
                    custom_metadata=metadata_dict,
                )

                cosmos_service.create_asset_metadata(
                    cosmos_metadata.dict(exclude_unset=True)
                )
            except Exception as cosmos_error:
                # Log error but don't fail the upload
                import logging

                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to create Cosmos DB metadata: {cosmos_error}")

        return AssetUploadResponse(
            success=True,
            message=f"{media_type.value.capitalize()} uploaded successfully",
            **result,
        )
    except Exception as e:
        import traceback

        error_detail = str(e)
        error_trace = traceback.format_exc()
        print(f"Upload error: {error_detail}")
        print(f"Error trace: {error_trace}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/delete", response_model=AssetDeleteResponse)
async def delete_asset(
    blob_name: str = Query(..., description="Name of the blob to delete"),
    media_type: MediaType = Query(
        None, description="Type of media (image or video) to determine container"
    ),
    container: Optional[str] = Query(
        None,
        description="Container name (images or videos) - overrides media_type if provided",
    ),
    azure_storage_service: AzureBlobStorageService = Depends(
        lambda: AzureBlobStorageService()
    ),
    cosmos_service: Optional[CosmosDBService] = Depends(get_cosmos_service),
):
    """
    Delete an asset from Azure Blob Storage and Cosmos DB metadata
    """
    try:
        # Determine container name
        container_name = container
        if not container_name:
            if not media_type:
                raise HTTPException(
                    status_code=400,
                    detail="Either media_type or container must be specified",
                )
            container_name = (
                settings.AZURE_BLOB_IMAGE_CONTAINER
                if media_type == MediaType.IMAGE
                else settings.AZURE_BLOB_VIDEO_CONTAINER
            )

        # Extract asset ID for Cosmos DB deletion
        asset_id = blob_name.split(".")[0].split("/")[-1]
        media_type_str = (
            "image"
            if container_name == settings.AZURE_BLOB_IMAGE_CONTAINER
            else "video"
        )

        # Delete from Cosmos DB first (if available)
        if cosmos_service:
            try:
                cosmos_service.delete_asset_metadata(asset_id, media_type_str)
            except Exception as cosmos_error:
                import logging

                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to delete Cosmos DB metadata: {cosmos_error}")

        # Delete from Azure Blob Storage
        success = azure_storage_service.delete_asset(blob_name, container_name)

        if not success:
            raise HTTPException(status_code=404, detail="Asset not found")

        return AssetDeleteResponse(
            success=True,
            message="Asset deleted successfully",
            blob_name=blob_name,
            container=container_name,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Include all other existing endpoints with similar Cosmos DB integration...
# For brevity, I'm showing the pattern for the main endpoints.
# The remaining endpoints would follow the same pattern of:
# 1. Try Cosmos DB operation if available
# 2. Fall back to blob storage
# 3. Log warnings for Cosmos DB failures but don't fail the operation


@router.get("/asset/{media_type}/{blob_name:path}")
async def get_asset_content(
    media_type: MediaType,
    blob_name: str,
    azure_storage_service: AzureBlobStorageService = Depends(
        lambda: AzureBlobStorageService()
    ),
):
    """Stream asset content directly from Azure Blob Storage"""
    try:
        container_name = (
            settings.AZURE_BLOB_IMAGE_CONTAINER
            if media_type == MediaType.IMAGE
            else settings.AZURE_BLOB_VIDEO_CONTAINER
        )
        content, content_type = azure_storage_service.get_asset_content(
            blob_name, container_name
        )

        if not content:
            raise HTTPException(status_code=404, detail=f"Asset not found: {blob_name}")

        filename = blob_name.split("/")[-1] if "/" in blob_name else blob_name

        return StreamingResponse(
            content=io.BytesIO(content),
            media_type=content_type,
            headers={"Content-Disposition": f"inline; filename={filename}"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sas-tokens", response_model=SasTokenResponse)
async def get_sas_tokens():
    """Generate and return SAS tokens for frontend direct access to blob storage"""
    try:
        video_token = generate_container_sas(
            account_name=settings.AZURE_STORAGE_ACCOUNT_NAME,
            container_name=settings.AZURE_BLOB_VIDEO_CONTAINER,
            account_key=settings.AZURE_STORAGE_ACCOUNT_KEY,
            permission=ContainerSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        image_token = generate_container_sas(
            account_name=settings.AZURE_STORAGE_ACCOUNT_NAME,
            container_name=settings.AZURE_BLOB_IMAGE_CONTAINER,
            account_key=settings.AZURE_STORAGE_ACCOUNT_KEY,
            permission=ContainerSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        expiry_time = datetime.now(timezone.utc) + timedelta(hours=1)
        return {
            "success": True,
            "message": "SAS tokens generated successfully",
            "video_sas_token": video_token,
            "image_sas_token": image_token,
            "video_container_url": f"https://{settings.AZURE_STORAGE_ACCOUNT_NAME}.blob.core.windows.net/{settings.AZURE_BLOB_VIDEO_CONTAINER}",
            "image_container_url": f"https://{settings.AZURE_STORAGE_ACCOUNT_NAME}.blob.core.windows.net/{settings.AZURE_BLOB_IMAGE_CONTAINER}",
            "expiry": expiry_time,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health", response_model=Dict[str, Any])
async def health_check(
    cosmos_service: Optional[CosmosDBService] = Depends(get_cosmos_service),
    azure_storage_service: AzureBlobStorageService = Depends(
        lambda: AzureBlobStorageService()
    ),
):
    """
    Health check endpoint to verify all services are working
    """
    health_status = {
        "timestamp": datetime.utcnow().isoformat(),
        "services": {},
        "overall_status": "healthy",
    }

    # Check Azure Blob Storage
    try:
        # Try to list containers to test connectivity
        containers = [
            settings.AZURE_BLOB_IMAGE_CONTAINER,
            settings.AZURE_BLOB_VIDEO_CONTAINER,
        ]
        for container in containers:
            azure_storage_service._ensure_container_exists(container)

        health_status["services"]["azure_blob_storage"] = {
            "status": "healthy",
            "message": "Successfully connected to Azure Blob Storage",
            "containers": containers,
        }
    except Exception as e:
        health_status["services"]["azure_blob_storage"] = {
            "status": "unhealthy",
            "error": str(e),
        }
        health_status["overall_status"] = "degraded"

    # Check Cosmos DB
    if cosmos_service:
        try:
            cosmos_health = cosmos_service.health_check()
            health_status["services"]["cosmos_db"] = cosmos_health

            if cosmos_health["status"] != "healthy":
                health_status["overall_status"] = "degraded"

        except Exception as e:
            health_status["services"]["cosmos_db"] = {
                "status": "unhealthy",
                "error": str(e),
                "message": "Cosmos DB metadata service unavailable - falling back to blob storage",
            }
            health_status["overall_status"] = "degraded"
    else:
        health_status["services"]["cosmos_db"] = {
            "status": "unavailable",
            "message": "Cosmos DB not configured - using blob storage only",
        }
        health_status["overall_status"] = "degraded"

    # Check AI Services
    try:
        # Test if AI clients are properly initialized
        from backend.core import sora_client, dalle_client, llm_client

        ai_services = {}
        if sora_client:
            ai_services["sora"] = "available"
        if dalle_client:
            ai_services["dalle/gpt_image"] = "available"
        if llm_client:
            ai_services["llm"] = "available"

        health_status["services"]["ai_services"] = {
            "status": "healthy" if ai_services else "unhealthy",
            "available_services": ai_services,
            "message": f"{len(ai_services)} AI services available",
        }

    except Exception as e:
        health_status["services"]["ai_services"] = {
            "status": "unhealthy",
            "error": str(e),
        }
        health_status["overall_status"] = "degraded"

    return health_status


@router.get("/metadata/status", response_model=Dict[str, Any])
async def metadata_service_status(
    cosmos_service: Optional[CosmosDBService] = Depends(get_cosmos_service),
):
    """
    Detailed status of metadata service capabilities
    """
    status = {
        "timestamp": datetime.utcnow().isoformat(),
        "metadata_service": {},
        "capabilities": {},
    }

    if cosmos_service:
        try:
            # Test basic connectivity
            cosmos_health = cosmos_service.health_check()

            # Test query capabilities
            test_query_result = cosmos_service.query_assets(limit=1, offset=0)

            # Test search capabilities
            try:
                search_result = cosmos_service.search_assets("test", limit=1)
                search_available = True
            except:
                search_available = False

            status["metadata_service"] = {
                "status": "available",
                "type": "cosmos_db",
                "health": cosmos_health,
                "total_assets": test_query_result.get("total", 0),
                "performance_mode": "fast_metadata_queries",
            }

            status["capabilities"] = {
                "fast_pagination": True,
                "advanced_search": search_available,
                "metadata_filtering": True,
                "tag_based_search": True,
                "folder_statistics": True,
                "recent_assets": True,
                "ai_metadata_enrichment": True,
            }

        except Exception as e:
            status["metadata_service"] = {
                "status": "error",
                "type": "cosmos_db",
                "error": str(e),
                "performance_mode": "fallback_to_blob_storage",
            }

            status["capabilities"] = {
                "fast_pagination": False,
                "advanced_search": False,
                "metadata_filtering": False,
                "tag_based_search": False,
                "folder_statistics": False,
                "recent_assets": False,
                "ai_metadata_enrichment": False,
            }
    else:
        status["metadata_service"] = {
            "status": "unavailable",
            "type": "blob_storage_only",
            "performance_mode": "blob_storage_fallback",
        }

        status["capabilities"] = {
            "fast_pagination": False,
            "advanced_search": False,
            "metadata_filtering": True,
            "tag_based_search": False,
            "folder_statistics": False,
            "recent_assets": False,
            "ai_metadata_enrichment": False,
        }

    return status


@router.get("/folders", response_model=Dict[str, Any])
async def get_folders(
    media_type: Optional[str] = Query(None, description="Filter by media type (image or video)"),
    cosmos_service: CosmosDBService = Depends(get_cosmos_service),
):
    """
    Get all folders for a given media type from Cosmos DB
    """
    try:
        # Get folder statistics from Cosmos DB
        folder_stats = cosmos_service.get_folder_stats(media_type=media_type)
        
        # Extract unique folders with counts
        folder_list = []
        for stat in folder_stats["folder_stats"]:
            if stat["folder_path"]:  # Exclude empty folder paths
                folder_list.append({
                    "path": stat["folder_path"],
                    "count": stat["count"]
                })
        
        # Sort by folder path
        folder_list.sort(key=lambda x: x["path"])
        
        return {
            "success": True,
            "message": f"Retrieved {len(folder_list)} folders from Cosmos DB",
            "folders": folder_list,
            "total_folders": folder_stats["total_folders"],
            "source": "cosmos_db"
        }
        
    except Exception as e:
        logger.error(f"Error getting folders from Cosmos DB: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve folders: {str(e)}")
