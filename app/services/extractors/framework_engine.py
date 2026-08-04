import json
import logging

logger = logging.getLogger(__name__)

class FrameworkRuleEngine:
    @staticmethod
    def detect(file_contents: dict) -> dict:
        """
        File contents is a dict: {"package.json": "...", "requirements.txt": "..."}
        Returns detected language and frameworks.
        """
        frameworks = []
        language = "Unknown"
        
        # JS/TS
        package_json = file_contents.get("package.json")
        if package_json:
            try:
                data = json.loads(package_json)
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                
                if "typescript" in deps: language = "TypeScript"
                elif language == "Unknown": language = "JavaScript"
                
                if "react" in deps: frameworks.append({"name": "React", "version": deps["react"]})
                if "next" in deps: frameworks.append({"name": "Next.js", "version": deps["next"]})
                if "vue" in deps: frameworks.append({"name": "Vue", "version": deps["vue"]})
                if "@angular/core" in deps: frameworks.append({"name": "Angular", "version": deps["@angular/core"]})
                if "@nestjs/core" in deps: frameworks.append({"name": "NestJS", "version": deps["@nestjs/core"]})
                if "express" in deps: frameworks.append({"name": "Express", "version": deps["express"]})
            except Exception as e:
                logger.warning(f"Error parsing package.json: {e}")

        # Python
        requirements = file_contents.get("requirements.txt")
        if requirements:
            language = "Python"
            reqs = requirements.lower()
            if "django" in reqs: frameworks.append({"name": "Django", "version": "unknown"})
            if "fastapi" in reqs: frameworks.append({"name": "FastAPI", "version": "unknown"})
            if "flask" in reqs: frameworks.append({"name": "Flask", "version": "unknown"})
            if "tensorflow" in reqs: frameworks.append({"name": "TensorFlow", "version": "unknown"})
            if "torch" in reqs: frameworks.append({"name": "PyTorch", "version": "unknown"})

        # C#
        csproj = file_contents.get("csproj")
        if csproj:
            language = "C#"
            content = csproj.lower()
            if "microsoft.aspnetcore" in content: frameworks.append({"name": "ASP.NET Core", "version": "unknown"})
            if "microsoft.entityframeworkcore" in content: frameworks.append({"name": "Entity Framework", "version": "unknown"})
            if "blazor" in content: frameworks.append({"name": "Blazor", "version": "unknown"})

        # Java
        pom = file_contents.get("pom.xml")
        if pom:
            language = "Java"
            content = pom.lower()
            if "spring-boot" in content: frameworks.append({"name": "Spring Boot", "version": "unknown"})
            if "hibernate" in content: frameworks.append({"name": "Hibernate", "version": "unknown"})

        return {
            "language": language,
            "frameworks": frameworks
        }
