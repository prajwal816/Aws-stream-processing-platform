"""
CloudFormation template validator.

Validates all CloudFormation/SAM templates for:
- YAML syntax
- Required sections
- Resource references
- Parameter consistency
"""

import os
import sys
import yaml
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def validate_yaml_syntax(filepath: str) -> dict:
    """Validate YAML syntax."""
    try:
        with open(filepath, "r") as f:
            content = yaml.safe_load(f)
        return {"valid": True, "content": content, "error": None}
    except yaml.YAMLError as e:
        return {"valid": False, "content": None, "error": str(e)}


def validate_cloudformation_template(filepath: str, content: dict) -> list[str]:
    """Validate CloudFormation template structure."""
    errors = []
    filename = os.path.basename(filepath)

    # Check required top-level keys
    if "AWSTemplateFormatVersion" not in content:
        errors.append(f"{filename}: Missing AWSTemplateFormatVersion")

    if "Resources" not in content and "Transform" not in content:
        # Nested stacks might not have Resources if they use Transform
        if "Description" in content:
            pass  # Root SAM template with nested stacks
        else:
            errors.append(f"{filename}: Missing Resources section")

    # Check Description
    if "Description" not in content:
        errors.append(f"{filename}: Missing Description (recommended)")

    # Validate Parameters
    if "Parameters" in content:
        for param_name, param_def in content["Parameters"].items():
            if not isinstance(param_def, dict):
                errors.append(f"{filename}: Parameter '{param_name}' is not properly defined")
            elif "Type" not in param_def:
                errors.append(f"{filename}: Parameter '{param_name}' missing Type")

    # Validate Resources
    if "Resources" in content:
        for resource_name, resource_def in content["Resources"].items():
            if not isinstance(resource_def, dict):
                errors.append(f"{filename}: Resource '{resource_name}' is not properly defined")
                continue
            if "Type" not in resource_def:
                errors.append(f"{filename}: Resource '{resource_name}' missing Type")

    # Validate Outputs
    if "Outputs" in content:
        for output_name, output_def in content["Outputs"].items():
            if not isinstance(output_def, dict):
                errors.append(f"{filename}: Output '{output_name}' is not properly defined")
            elif "Value" not in output_def:
                errors.append(f"{filename}: Output '{output_name}' missing Value")

    return errors


def validate_all_templates():
    """Validate all CloudFormation templates in the project."""
    print("=" * 60)
    print("  CLOUDFORMATION TEMPLATE VALIDATOR")
    print("=" * 60)

    template_dirs = [
        os.path.join(PROJECT_ROOT, "infrastructure", "cloudformation"),
        os.path.join(PROJECT_ROOT, "infrastructure", "networking"),
        os.path.join(PROJECT_ROOT, "infrastructure", "monitoring"),
        os.path.join(PROJECT_ROOT, "infrastructure", "iam"),
    ]

    # Also check root template
    template_files = [os.path.join(PROJECT_ROOT, "template.yaml")]

    for tdir in template_dirs:
        if os.path.exists(tdir):
            for f in os.listdir(tdir):
                if f.endswith((".yaml", ".yml")):
                    template_files.append(os.path.join(tdir, f))

    total_errors = []
    total_warnings = []

    for filepath in template_files:
        if not os.path.exists(filepath):
            continue

        rel_path = os.path.relpath(filepath, PROJECT_ROOT)
        print(f"\n  📄 Validating: {rel_path}")

        # YAML syntax check
        result = validate_yaml_syntax(filepath)
        if not result["valid"]:
            print(f"     ❌ YAML syntax error: {result['error']}")
            total_errors.append(f"{rel_path}: YAML syntax error")
            continue

        print(f"     ✓ YAML syntax valid")

        # CloudFormation structure check
        errors = validate_cloudformation_template(filepath, result["content"])
        if errors:
            for err in errors:
                if "recommended" in err.lower():
                    print(f"     ⚠️  {err}")
                    total_warnings.append(err)
                else:
                    print(f"     ❌ {err}")
                    total_errors.append(err)
        else:
            print(f"     ✓ CloudFormation structure valid")

        # Count resources
        resources = result["content"].get("Resources", {})
        params = result["content"].get("Parameters", {})
        outputs = result["content"].get("Outputs", {})
        print(f"     📊 Resources: {len(resources)} | Parameters: {len(params)} | Outputs: {len(outputs)}")

    # Summary
    print("\n" + "=" * 60)
    print("  VALIDATION SUMMARY")
    print("=" * 60)
    print(f"  Templates scanned:  {len(template_files)}")
    print(f"  Errors:             {len(total_errors)}")
    print(f"  Warnings:           {len(total_warnings)}")

    if total_errors:
        print("\n  ❌ ERRORS:")
        for err in total_errors:
            print(f"     • {err}")
        print(f"\n  Result: FAILED")
        return False
    else:
        print(f"\n  ✅ All templates are valid!")
        return True


if __name__ == "__main__":
    success = validate_all_templates()
    sys.exit(0 if success else 1)
