import boto3
import json
from rich.console import Console
from rich.table import Table

console = Console()

def scout_infrastructure():
    console.print("[bold cyan]◢ ◤ CLOUD DISCOVERY SCOUT v1.0[/bold cyan]\n")
    
    # 1. Identitas Akun
    sts = boto3.client('sts')
    identity = sts.get_caller_identity()
    console.print(f"[green]✔ Identity Found:[/green] {identity['Arn']}")
    
    # 2. Pemindaian Region & Model Bedrock (API Research)
    ec2 = boto3.client('ec2', region_name='us-east-1')
    regions = [r['RegionName'] for r in ec2.describe_regions()['Regions']]
    
    table = Table(title="Global API Research")
    table.add_column("Region", style="cyan")
    table.add_column("Bedrock Status", style="magenta")

    for region in regions[:10]: # Batasi 10 region untuk kecepatan
        try:
            br = boto3.client('bedrock', region_name=region)
            br.list_foundation_models()
            table.add_row(region, "✅ API Access Active")
        except Exception as e:
            table.add_row(region, "❌ Access Denied")
            
    console.print(table)

if __name__ == "__main__":
    scout_infrastructure()
