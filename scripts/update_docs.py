def update_readme():
    with open("README.md", "a") as f:
        f.write("

## Auto-Generated Docs
")
        f.write("Last updated: today
")
        f.write("- API Health: /health
")
        f.write("- Docs: /docs
")

if __name__ == "__main__":
    update_readme()
