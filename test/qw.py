import kagglehub

# Download latest version
path = kagglehub.dataset_download(
    "ohagwucollinspatrick/amini-cocoa-contamination-dataset"
)

print("Path to dataset files:", path)
