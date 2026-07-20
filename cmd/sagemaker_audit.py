import boto3
from rich.console import Console
from rich.table import Table

console = Console()
sm = boto3.client('sagemaker', region_name='us-east-1')

def audit_sagemaker():
    table = Table(title="SageMaker Deep Audit")
    table.add_column("Resource Type", style="cyan")
    table.add_column("Detail", style="magenta")

    # Cek Models
    models = sm.list_models()
    table.add_row("Models", str(len(models['Models'])))
    
    # Cek Endpoints
    endpoints = sm.list_endpoints()
    table.add_row("Endpoints", str(len(endpoints['Endpoints'])))
    
    # Cek Notebook Instances
    notebooks = sm.list_notebook_instances()
    table.add_row("Notebooks", str(len(notebooks['NotebookInstances'])))

    console.print(table)

if __name__ == "__main__":
    audit_sagemaker()
