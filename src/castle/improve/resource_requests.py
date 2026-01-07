from __future__ import annotations
import json
import datetime as dt
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict
from enum import Enum


class ResourceType(Enum):
    """Types of resources that can be requested."""
    API = "api"
    DATA_SOURCE = "data_source"
    LIBRARY = "library"
    INFRASTRUCTURE = "infrastructure"
    FEATURE = "feature"


class Priority(Enum):
    """Request priority."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ResourceRequest:
    """A request for a new resource/capability."""
    request_id: str
    timestamp: dt.datetime
    resource_type: ResourceType
    priority: Priority
    
    title: str
    description: str
    justification: str
    
    analysis: str
    expected_improvement: str
    cost_estimate: str
    
    implementation_notes: str
    alternatives: List[str]
    
    discovered_during_run: str
    
    status: str = "pending"
    operator_notes: str = ""


class ResourceRequestManager:
    """Manage resource requests discovered during improvement cycles."""
    
    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self.requests: List[ResourceRequest] = []
        self.load()
    
    def create_request(
        self,
        resource_type: ResourceType,
        priority: Priority,
        title: str,
        description: str,
        justification: str,
        analysis: str,
        expected_improvement: str,
        discovered_during_run: str,
        cost_estimate: str = "Unknown",
        implementation_notes: str = "",
        alternatives: List[str] = None
    ) -> ResourceRequest:
        """Create a new resource request."""
        request = ResourceRequest(
            request_id=f"REQ-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}",
            timestamp=dt.datetime.now(dt.timezone.utc),
            resource_type=resource_type,
            priority=priority,
            title=title,
            description=description,
            justification=justification,
            analysis=analysis,
            expected_improvement=expected_improvement,
            cost_estimate=cost_estimate,
            implementation_notes=implementation_notes,
            alternatives=alternatives or [],
            discovered_during_run=discovered_during_run
        )
        
        self.requests.append(request)
        self.save()
        
        return request
    
    def get_pending_requests(self) -> List[ResourceRequest]:
        """Get all pending requests."""
        return [r for r in self.requests if r.status == "pending"]
    
    def approve_request(self, request_id: str, operator_notes: str = ""):
        """Operator approves a request."""
        for req in self.requests:
            if req.request_id == request_id:
                req.status = "approved"
                req.operator_notes = operator_notes
                self.save()
                break
    
    def reject_request(self, request_id: str, reason: str):
        """Operator rejects a request."""
        for req in self.requests:
            if req.request_id == request_id:
                req.status = "rejected"
                req.operator_notes = reason
                self.save()
                break
    
    def mark_implemented(self, request_id: str):
        """Mark a request as implemented."""
        for req in self.requests:
            if req.request_id == request_id:
                req.status = "implemented"
                self.save()
                break
    
    def save(self):
        """Save requests to disk."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = []
        for req in self.requests:
            req_dict = asdict(req)
            req_dict['resource_type'] = req.resource_type.value
            req_dict['priority'] = req.priority.value
            req_dict['timestamp'] = req.timestamp.isoformat()
            data.append(req_dict)
        
        self.storage_path.write_text(json.dumps(data, indent=2), encoding='utf-8')
    
    def load(self):
        """Load requests from disk."""
        if not self.storage_path.exists():
            return
        
        try:
            data = json.loads(self.storage_path.read_text(encoding='utf-8'))
            
            self.requests = []
            for item in data:
                item['resource_type'] = ResourceType(item['resource_type'])
                item['priority'] = Priority(item['priority'])
                item['timestamp'] = dt.datetime.fromisoformat(item['timestamp'])
                self.requests.append(ResourceRequest(**item))
        except Exception as e:
            import logging
            logging.warning(f"Failed to load resource requests: {e}")
            self.requests = []
    
    def export_for_operator(self, output_path: Path):
        """Export pending requests in human-readable format."""
        pending = self.get_pending_requests()
        
        if not pending:
            output_path.write_text("# Resource Requests\n\nNo pending resource requests.\n", encoding='utf-8')
            return
        
        # Sort by priority
        priority_order = {Priority.CRITICAL: 0, Priority.HIGH: 1, Priority.MEDIUM: 2, Priority.LOW: 3}
        pending.sort(key=lambda r: priority_order[r.priority])
        
        lines = ["# RESOURCE REQUESTS - OPERATOR REVIEW\n"]
        lines.append(f"Generated: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
        lines.append(f"Total Pending: {len(pending)}\n")
        lines.append("\n" + "=" * 80 + "\n")
        
        for req in pending:
            lines.append(f"\n## {req.title}")
            lines.append(f"**Request ID:** `{req.request_id}`")
            lines.append(f"**Priority:** `{req.priority.value.upper()}`")
            lines.append(f"**Type:** `{req.resource_type.value}`")
            lines.append(f"**Discovered During:** {req.discovered_during_run}")
            lines.append(f"**Timestamp:** {req.timestamp.strftime('%Y-%m-%d %H:%M UTC')}\n")
            
            lines.append(f"### Description")
            lines.append(req.description + "\n")
            
            lines.append(f"### Justification")
            lines.append(req.justification + "\n")
            
            lines.append(f"### Expected Improvement")
            lines.append(req.expected_improvement + "\n")
            
            lines.append(f"### Cost Estimate")
            lines.append(req.cost_estimate + "\n")
            
            if req.implementation_notes:
                lines.append(f"### Implementation Notes")
                lines.append(req.implementation_notes + "\n")
            
            if req.alternatives:
                lines.append(f"### Alternatives")
                for alt in req.alternatives:
                    lines.append(f"- {alt}")
                lines.append("")
            
            lines.append("\n### Actions")
            lines.append(f"```bash")
            lines.append(f"castle resources approve {req.request_id}")
            lines.append(f"castle resources reject {req.request_id} --reason 'explanation'")
            lines.append("```\n")
            
            lines.append("\n" + "=" * 80 + "\n")
        
        output_path.write_text("\n".join(lines), encoding='utf-8')
