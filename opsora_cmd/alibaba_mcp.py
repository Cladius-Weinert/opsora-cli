#!/usr/bin/env python3
"""
Alibaba Cloud MCP Server
Provides tools for managing Alibaba Cloud resources via MCP.
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional

from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.acs_exception.exceptions import ClientException, ServerException
from aliyunsdkecs.request.v20140526 import (
    DescribeInstancesRequest,
    DescribeRegionsRequest,
    DescribeAvailableResourceRequest,
    StartInstanceRequest,
    StopInstanceRequest,
    RebootInstanceRequest,
    DescribeInstanceStatusRequest,
    DescribeInstanceTypesRequest,
)
from aliyunsdkvpc.request.v20160428 import (
    DescribeVpcsRequest,
    DescribeVSwitchesRequest,
    DescribeEipAddressesRequest,
)
from aliyunsdkrds.request.v20140815 import (
    DescribeDBInstancesRequest,
    DescribeDBInstanceAttributeRequest,
)
from aliyunsdkslb.request.v20140515 import (
    DescribeLoadBalancersRequest,
    DescribeLoadBalancerAttributeRequest,
)


class AlibabaCloudMCP:
    def __init__(self):
        self.access_key_id = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID")
        self.access_key_secret = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
        self.region = os.getenv("ALIBABA_CLOUD_REGION", "cn-hangzhou")
        self.client: Optional[AcsClient] = None
        self._init_client()

    def _init_client(self):
        if self.access_key_id and self.access_key_secret:
            self.client = AcsClient(
                self.access_key_id,
                self.access_key_secret,
                self.region
            )

    def _get_client(self, region_id: Optional[str] = None) -> Optional[AcsClient]:
        """Get client for specific region, or default client."""
        target_region = region_id or self.region
        if target_region == self.region:
            return self.client
        if self.access_key_id and self.access_key_secret:
            return AcsClient(self.access_key_id, self.access_key_secret, target_region)
        return None

    def _execute(self, request, region_id: Optional[str] = None) -> Dict[str, Any]:
        client = self._get_client(region_id)
        if not client:
            return {"error": "Client not initialized. Check credentials."}
        try:
            response = client.do_action_with_exception(request)
            return json.loads(response.decode('utf-8'))
        except (ClientException, ServerException) as e:
            return {"error": str(e), "code": getattr(e, 'error_code', 'Unknown')}

    # ECS Tools
    def describe_instances(self, region_id: Optional[str] = None) -> Dict[str, Any]:
        """List ECS instances in a region."""
        req = DescribeInstancesRequest.DescribeInstancesRequest()
        req.set_accept_format('json')
        return self._execute(req, region_id)

    def describe_instance_status(self, region_id: Optional[str] = None, instance_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Get status of specific instances."""
        req = DescribeInstanceStatusRequest.DescribeInstanceStatusRequest()
        req.set_accept_format('json')
        if instance_ids:
            req.set_InstanceIds(json.dumps(instance_ids))
        return self._execute(req, region_id)

    def start_instance(self, instance_id: str, region_id: Optional[str] = None) -> Dict[str, Any]:
        """Start an ECS instance."""
        req = StartInstanceRequest.StartInstanceRequest()
        req.set_accept_format('json')
        req.set_InstanceId(instance_id)
        return self._execute(req, region_id)

    def stop_instance(self, instance_id: str, region_id: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
        """Stop an ECS instance."""
        req = StopInstanceRequest.StopInstanceRequest()
        req.set_accept_format('json')
        req.set_InstanceId(instance_id)
        req.set_ForceStop(force)
        return self._execute(req, region_id)

    def reboot_instance(self, instance_id: str, region_id: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
        """Reboot an ECS instance."""
        req = RebootInstanceRequest.RebootInstanceRequest()
        req.set_accept_format('json')
        req.set_InstanceId(instance_id)
        req.set_ForceStop(force)
        return self._execute(req, region_id)

    def describe_regions(self) -> Dict[str, Any]:
        """List all available regions."""
        req = DescribeRegionsRequest.DescribeRegionsRequest()
        req.set_accept_format('json')
        return self._execute(req)

    def describe_instance_types(self, region_id: Optional[str] = None) -> Dict[str, Any]:
        """List available instance types."""
        req = DescribeInstanceTypesRequest.DescribeInstanceTypesRequest()
        req.set_accept_format('json')
        return self._execute(req, region_id)

    def describe_available_resource(self, region_id: str, zone_id: Optional[str] = None,
                                     instance_type: Optional[str] = None) -> Dict[str, Any]:
        """Check resource availability for instance types."""
        req = DescribeAvailableResourceRequest.DescribeAvailableResourceRequest()
        req.set_accept_format('json')
        req.set_DestinationResource("InstanceType")
        if zone_id:
            req.set_ZoneId(zone_id)
        if instance_type:
            req.set_InstanceType(instance_type)
        return self._execute(req, region_id)

    # VPC Tools
    def describe_vpcs(self, region_id: Optional[str] = None, vpc_id: Optional[str] = None) -> Dict[str, Any]:
        """List VPCs."""
        req = DescribeVpcsRequest.DescribeVpcsRequest()
        req.set_accept_format('json')
        if vpc_id:
            req.set_VpcId(vpc_id)
        return self._execute(req, region_id)

    def describe_vswitches(self, region_id: Optional[str] = None, vpc_id: Optional[str] = None,
                            zone_id: Optional[str] = None) -> Dict[str, Any]:
        """List VSwitches (subnets)."""
        req = DescribeVSwitchesRequest.DescribeVSwitchesRequest()
        req.set_accept_format('json')
        if vpc_id:
            req.set_VpcId(vpc_id)
        if zone_id:
            req.set_ZoneId(zone_id)
        return self._execute(req, region_id)

    def describe_eips(self, region_id: Optional[str] = None) -> Dict[str, Any]:
        """List Elastic IPs."""
        req = DescribeEipAddressesRequest.DescribeEipAddressesRequest()
        req.set_accept_format('json')
        return self._execute(req, region_id)

    # RDS Tools
    def describe_rds_instances(self, region_id: Optional[str] = None) -> Dict[str, Any]:
        """List RDS instances."""
        req = DescribeDBInstancesRequest.DescribeDBInstancesRequest()
        req.set_accept_format('json')
        return self._execute(req, region_id)

    def describe_rds_instance(self, db_instance_id: str, region_id: Optional[str] = None) -> Dict[str, Any]:
        """Get detailed RDS instance info."""
        req = DescribeDBInstanceAttributeRequest.DescribeDBInstanceAttributeRequest()
        req.set_accept_format('json')
        req.set_DBInstanceId(db_instance_id)
        return self._execute(req, region_id)

    # SLB Tools
    def describe_load_balancers(self, region_id: Optional[str] = None) -> Dict[str, Any]:
        """List SLB (Load Balancers)."""
        req = DescribeLoadBalancersRequest.DescribeLoadBalancersRequest()
        req.set_accept_format('json')
        return self._execute(req, region_id)

    def describe_load_balancer(self, load_balancer_id: str, region_id: Optional[str] = None) -> Dict[str, Any]:
        """Get detailed SLB info."""
        req = DescribeLoadBalancerAttributeRequest.DescribeLoadBalancerAttributeRequest()
        req.set_accept_format('json')
        req.set_LoadBalancerId(load_balancer_id)
        return self._execute(req, region_id)


# MCP Tool Definitions
TOOLS = [
    {
        "name": "alibaba_describe_instances",
        "description": "List ECS instances in a region",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region_id": {"type": "string", "description": "Region ID (default: cn-hangzhou)"}
            }
        }
    },
    {
        "name": "alibaba_describe_instance_status",
        "description": "Get status of specific ECS instances",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region_id": {"type": "string", "description": "Region ID"},
                "instance_ids": {"type": "array", "items": {"type": "string"}, "description": "List of instance IDs"}
            }
        }
    },
    {
        "name": "alibaba_start_instance",
        "description": "Start an ECS instance",
        "inputSchema": {
            "type": "object",
            "properties": {
                "instance_id": {"type": "string", "description": "Instance ID to start"},
                "region_id": {"type": "string", "description": "Region ID"}
            },
            "required": ["instance_id"]
        }
    },
    {
        "name": "alibaba_stop_instance",
        "description": "Stop an ECS instance",
        "inputSchema": {
            "type": "object",
            "properties": {
                "instance_id": {"type": "string", "description": "Instance ID to stop"},
                "region_id": {"type": "string", "description": "Region ID"},
                "force": {"type": "boolean", "description": "Force stop", "default": False}
            },
            "required": ["instance_id"]
        }
    },
    {
        "name": "alibaba_reboot_instance",
        "description": "Reboot an ECS instance",
        "inputSchema": {
            "type": "object",
            "properties": {
                "instance_id": {"type": "string", "description": "Instance ID to reboot"},
                "region_id": {"type": "string", "description": "Region ID"},
                "force": {"type": "boolean", "description": "Force reboot", "default": False}
            },
            "required": ["instance_id"]
        }
    },
    {
        "name": "alibaba_describe_regions",
        "description": "List all available Alibaba Cloud regions",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "alibaba_describe_instance_types",
        "description": "List available ECS instance types in a region",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region_id": {"type": "string", "description": "Region ID"}
            }
        }
    },
    {
        "name": "alibaba_check_resource_availability",
        "description": "Check if specific instance types are available in a region/zone",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region_id": {"type": "string", "description": "Region ID"},
                "zone_id": {"type": "string", "description": "Zone ID (optional)"},
                "instance_type": {"type": "string", "description": "Instance type to check (optional)"}
            },
            "required": ["region_id"]
        }
    },
    {
        "name": "alibaba_describe_vpcs",
        "description": "List VPCs (Virtual Private Clouds)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region_id": {"type": "string", "description": "Region ID"},
                "vpc_id": {"type": "string", "description": "Specific VPC ID (optional)"}
            }
        }
    },
    {
        "name": "alibaba_describe_vswitches",
        "description": "List VSwitches (subnets) in a VPC",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region_id": {"type": "string", "description": "Region ID"},
                "vpc_id": {"type": "string", "description": "VPC ID (optional)"},
                "zone_id": {"type": "string", "description": "Zone ID (optional)"}
            }
        }
    },
    {
        "name": "alibaba_describe_eips",
        "description": "List Elastic IP addresses",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region_id": {"type": "string", "description": "Region ID"}
            }
        }
    },
    {
        "name": "alibaba_describe_rds_instances",
        "description": "List RDS database instances",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region_id": {"type": "string", "description": "Region ID"}
            }
        }
    },
    {
        "name": "alibaba_describe_rds_instance",
        "description": "Get detailed info for a specific RDS instance",
        "inputSchema": {
            "type": "object",
            "properties": {
                "db_instance_id": {"type": "string", "description": "RDS instance ID"},
                "region_id": {"type": "string", "description": "Region ID"}
            },
            "required": ["db_instance_id"]
        }
    },
    {
        "name": "alibaba_describe_load_balancers",
        "description": "List SLB (Server Load Balancer) instances",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region_id": {"type": "string", "description": "Region ID"}
            }
        }
    },
    {
        "name": "alibaba_describe_load_balancer",
        "description": "Get detailed info for a specific SLB instance",
        "inputSchema": {
            "type": "object",
            "properties": {
                "load_balancer_id": {"type": "string", "description": "SLB instance ID"},
                "region_id": {"type": "string", "description": "Region ID"}
            },
            "required": ["load_balancer_id"]
        }
    },
]


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Alibaba Cloud MCP Server")
    parser.add_argument("--list-tools", action="store_true", help="List available tools")
    parser.add_argument("--call", type=str, help="Call a tool (JSON format)")
    args = parser.parse_args()

    if args.list_tools:
        print(json.dumps({"tools": TOOLS}, indent=2))
        return

    if args.call:
        try:
            call_data = json.loads(args.call)
            tool_name = call_data.get("name")
            arguments = call_data.get("arguments", {})

            mcp = AlibabaCloudMCP()

            # Map tool names to methods
            method_map = {
                "alibaba_describe_instances": mcp.describe_instances,
                "alibaba_describe_instance_status": mcp.describe_instance_status,
                "alibaba_start_instance": mcp.start_instance,
                "alibaba_stop_instance": mcp.stop_instance,
                "alibaba_reboot_instance": mcp.reboot_instance,
                "alibaba_describe_regions": mcp.describe_regions,
                "alibaba_describe_instance_types": mcp.describe_instance_types,
                "alibaba_check_resource_availability": mcp.describe_available_resource,
                "alibaba_describe_vpcs": mcp.describe_vpcs,
                "alibaba_describe_vswitches": mcp.describe_vswitches,
                "alibaba_describe_eips": mcp.describe_eips,
                "alibaba_describe_rds_instances": mcp.describe_rds_instances,
                "alibaba_describe_rds_instance": mcp.describe_rds_instance,
                "alibaba_describe_load_balancers": mcp.describe_load_balancers,
                "alibaba_describe_load_balancer": mcp.describe_load_balancer,
            }

            if tool_name not in method_map:
                print(json.dumps({"error": f"Unknown tool: {tool_name}"}))
                return

            method = method_map[tool_name]
            result = method(**arguments)
            print(json.dumps(result, indent=2))

        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON: {e}"}))
        except Exception as e:
            print(json.dumps({"error": str(e)}))


if __name__ == "__main__":
    main()