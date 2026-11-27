"""CLI for MCP Elicitation Form Router."""
import argparse
import json
from .core import ElicitationFormBuilder, ElicitationRouter


def main():
    parser = argparse.ArgumentParser(description="MCP Elicitation Form Router CLI")
    parser.add_argument("--env", default="staging", choices=["staging", "prod"], help="Deployment target")
    parser.add_argument("--replicas", type=int, default=3, help="Replica count")
    args = parser.parse_args()

    schema = (
        ElicitationFormBuilder()
        .add_string("env", title="Environment", enum=["staging", "prod"], default="staging")
        .add_integer("replicas", title="Replicas", minimum=1, maximum=10, default=1)
        .build()
    )
    router = ElicitationRouter()
    payload = router.create_request("elicit-1", "Confirm rollout", schema)
    res = router.submit_response("elicit-1", "accept", {"env": args.env, "replicas": args.replicas})
    print(json.dumps({"request": payload, "merged": res.merged_content}, indent=2))


if __name__ == "__main__":
    main()
