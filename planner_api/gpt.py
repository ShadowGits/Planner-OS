import json
import os
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import JSONResponse

gpt_router = APIRouter(tags=["GPT OpenAPI"])

def _type_to_schema(annotation: str | None) -> dict:
    if not annotation:
        return {"type": "string"}
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
    
    tool_names = []
    schemas_text = []
    
    for tool in manifest.get("tools", []):
        tool_name = tool["name"]
        description = tool.get("description", "")
        
        tool_names.append(tool_name)
        
        properties = {}
        for param in tool.get("parameters", []):
            param_name = param["name"]
            param_type = _type_to_schema(param.get("annotation", "str"))
            req = "*" if param.get("required") else ""
            properties[f"{param_name}{req}"] = param_type["type"]
            
        schemas_text.append(f"- {tool_name}: {description}\n  args: {json.dumps(properties)}")
        
    full_description = (
        "Invoke a Planner OS tool. You MUST specify the exact tool_name in the path, "
        "and pass the correct arguments as a JSON object in the request body.\n\n"
        "AVAILABLE TOOLS AND THEIR ARGUMENT SCHEMAS (args with * are required):\n"
        + "\n".join(schemas_text)
    )

    openapi["paths"]["/api/v1/tools/{tool_name}/invoke"] = {
        "post": {
            "summary": "Invoke any Planner OS Tool",
            "description": full_description,
            "operationId": "invoke_planner_os_tool",
            "parameters": [
                {
                    "name": "tool_name",
                    "in": "path",
                    "required": True,
                    "schema": {
                        "type": "string",
                        "enum": tool_names
                    },
                    "description": "The exact name of the tool to invoke"
                }
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "workspace_id": {
                                    "type": "string",
                                    "format": "uuid",
                                    "description": "The target workspace ID"
                                },
                                "arguments": {
                                    "type": "object",
                                    "description": "A JSON object containing the arguments for the specific tool."
                                }
                            },
                            "required": ["workspace_id", "arguments"]
                        }
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
