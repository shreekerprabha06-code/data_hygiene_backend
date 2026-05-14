from pydantic import BaseModel, ConfigDict, Field
from typing import List, Dict, Any, Optional

class ApproveSuggestionRequest(BaseModel):
    model_config = ConfigDict(
        extra='allow',
        json_schema_extra={
            "example": {
                "execution_id": "uuid-12345",
                "field_name": "CPUModel",
                "accepted_value": "9575F",
                "currentStatus": "Accepted",
                "coreCount": "128",
                "masterlist_id": "67b97e9de296d92efb1bd7e4",
                "metadata": {
                    "Architecture": "x86-64",
                    "CCDCount": "16",
                    "CPU(s)": "128",
                    "CPUMaxMHz": "3700",
                    "Core(s)PerSocket": "64",
                    "CorePerCCD": "8",
                    "Family": "Turin",
                    "L3Cache": "512 MB",
                    "L3CacheInstances": "16",
                    "Microarchitecture": "Zen 5",
                    "Microcode": "0x1000000",
                    "Model": "9575F",
                    "PeakPerformance": "High",
                    "Socket(s)": "1",
                    "Technology": "4nm",
                    "Thread(s)PerCore": "2",
                    "num_L3": "16",
                    "cloudProvider": "AWS",
                    "BenchmarkType": "Nginx",
                    "BenchmarkCategory": "Web",
                    "sutType": "Server"
                }
            }
        }
    )
 
    execution_id: str
    field_name: str
    accepted_value: str
    currentStatus: str = "Accepted"
    coreCount: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class BatchExecutionRequest(BaseModel):
    execution_ids: List[str]

class RejectRecordRequest(BaseModel):
    execution_id: str
    currentStatus: str = "L0 Data"

class ReassignRecordItem(BaseModel):
    e_id: str
    assign_from: str
    assign_to: str

class ReassignRecordsRequest(BaseModel):
    assignments: List[ReassignRecordItem]

class DraftRecordRequest(BaseModel):
    model_config = ConfigDict(extra='allow')

    value: str
    currentStatus: str = "ON HOLD"
    id: Optional[str] = None
    execution_id: Optional[str] = None
    # Dynamic metadata container
    metadata: Dict[str, Any] = {}
    
    # Keeping named fields for backward compatibility and convenience
    family: Optional[str] = ""
    corecount: Optional[str] = ""
    cpumodel: Optional[str] = ""
    cloudprovider: Optional[str] = ""
    benchmarktype: Optional[str] = ""

    def get_merged_metadata(self) -> Dict[str, Any]:
        """Merges named fields and the generic metadata dict, including extra fields."""
        data = dict(self.metadata)
        
        # Capture all extra fields sent from the UI (e.g. 'Family', 'CPU(s)')
        if hasattr(self, 'model_extra') and self.model_extra:
            data.update(self.model_extra)

        # Only add named fields if they aren't already in the metadata dict and aren't empty
        if self.family and "Family" not in data: data["Family"] = self.family
        if self.corecount and "coreCount" not in data: data["coreCount"] = self.corecount
        if self.cpumodel and "CPUModel" not in data: data["CPUModel"] = self.cpumodel
        if self.cloudprovider and "cloudProvider" not in data: data["cloudProvider"] = self.cloudprovider
        if self.benchmarktype and "BenchmarkType" not in data: data["BenchmarkType"] = self.benchmarktype
        return data
