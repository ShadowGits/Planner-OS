import json
import os
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import JSONResponse

gpt_router = APIRouter(tags=["GPT OpenAPI"])

def _type_to_schema(annotation: str) -> dict:
    if "list[" in annotation or "list" in annotation:
        return {"type": "array", "items": {"type": "string"}}
    if "int" in annotation:
        return {"type": "integer"}
    if "float" in annotation:
        return {"type": "number"}
    if "bool" in annotation:
        return {"type": "boolean"}
    if "dict" in annotation or "dict[" in annotation:
        return {"type": "object"}
    return {"type": "string"}

from planner_api.manifest_data import MANIFEST_DATA

@gpt_router.get("/api/gpt/openapi.json")
def get_gpt_openapi():
    manifest = MANIFEST_DATA
        
    public_url = os.environ.get("PLANNER_WEB_APP_URL", "https://planner-os-nine.vercel.app").rstrip("/")
    
    openapi = {
        "openapi": "3.1.0",
        "info": {
            "title": "Planner OS",
            "description": "API for Planner OS tools",
            "version": "1.0.0"
        },
        "servers": [
            {
                "url": public_url
            }
        ],
        "paths": {}
    }
    
    for tool in manifest.get("tools", []):
        tool_name = tool["name"]
        description = tool.get("description", "")
        
        properties = {}
        required = []
        
        for param in tool.get("parameters", []):
            param_name = param["name"]
            param_type = _type_to_schema(param.get("annotation", "str"))
            
            # The manifest may contain None default values.
            if param.get("description"):
                param_type["description"] = param["description"]
                
            properties[param_name] = param_type
            
            if param.get("required"):
                required.append(param_name)
                
        request_schema = {
            "type": "object",
            "properties": {
                "workspace_id": {
                    "type": "string",
                    "format": "uuid",
                    "description": "The target workspace ID"
                },
                "arguments": {
                    "type": "object",
                    "properties": properties,
                }
            },
            "required": ["workspace_id", "arguments"]
        }
        
        if required:
            request_schema["properties"]["arguments"]["required"] = required
            
        openapi["paths"][f"/api/v1/tools/{tool_name}/invoke"] = {
            "post": {
                "summary": description,
                "operationId": tool_name,
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": request_schema
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Successful operation"
                    }
                }
            }
        }
        
    return JSONResponse(openapi)
