class StructureScanner:
    @staticmethod
    def scan_tree(tree_data: list) -> dict:
        """
        Scan github git tree to detect important folders and files
        """
        folders = set()
        files = set()
        
        for item in tree_data:
            path = item.get("path", "")
            type_ = item.get("type")
            
            if type_ == "tree":
                # Get root level folders or specific paths
                if "/" not in path:
                    folders.add(path.lower())
                elif path.startswith(".github/workflows"):
                    folders.add(".github/workflows")
            else:
                files.add(path.split("/")[-1].lower())
                
        return {
            "has_src": "src" in folders or "source" in folders,
            "has_test": "test" in folders or "tests" in folders or "spec" in folders,
            "has_docs": "docs" in folders,
            "has_docker": "docker" in folders or "dockerfile" in files,
            "has_cicd": ".github/workflows" in folders or ".travis.yml" in files or "jenkinsfile" in files,
            "important_files": files
        }

    @staticmethod
    def detect_cicd(scanner_result: dict) -> dict:
        """
        Detect CI/CD based on scanner result
        """
        files = scanner_result.get("important_files", set())
        has_workflows = scanner_result.get("has_cicd", False)
        
        tools = []
        if has_workflows or any(f.endswith(".yml") for f in files if "github" in f):
            tools.append("GitHub Actions")
        if "jenkinsfile" in files:
            tools.append("Jenkins")
        if ".travis.yml" in files:
            tools.append("Travis CI")
        if ".circleci" in files or ".circleci" in scanner_result.get("important_files", set()):
            tools.append("CircleCI")
            
        return {
            "ci_cd": len(tools) > 0,
            "tools": tools
        }
