$registry = "harbor.jypjt.local/jypjt"

$services = "product-service", "image-processing-service", "web-ui"

Write-Host "=== Harbor Image Release ==="

$NewTag = Read-Host "New tag (e.g. v0.1.4)"
$OldTag = Read-Host "Old tag (e.g. v0.1.3)"

Write-Host ""
Write-Host "Select services to rebuild (others will be re-tagged only)"
$rebuildFlags = @{}
foreach ($svc in $services) {
    $answer = Read-Host "  Rebuild ${svc}? (y/N)"
    $rebuildFlags[$svc] = ($answer -eq "y" -or $answer -eq "Y")
}

Write-Host ""
Write-Host "=== Plan ==="
foreach ($svc in $services) {
    if ($rebuildFlags[$svc]) {
        Write-Host "  ${svc} : REBUILD then push"
    } else {
        Write-Host "  ${svc} : RE-TAG (${OldTag} -> ${NewTag}) then push"
    }
}
$confirm = Read-Host "Proceed? (y/N)"
if ($confirm -ne "y" -and $confirm -ne "Y") {
    Write-Host "Cancelled."
    exit
}

foreach ($svc in $services) {
    $image = "${registry}/${svc}:${NewTag}"

    if ($rebuildFlags[$svc]) {
        Write-Host ""
        Write-Host "[BUILD] ${svc}"
        if ($svc -eq "web-ui") {
            docker build -f "web-ui/Dockerfile" -t $image "web-ui/"
        } else {
            docker build -f "${svc}/Dockerfile" -t $image "."
        }
    } else {
        Write-Host ""
        Write-Host "[TAG] ${svc} (${OldTag} -> ${NewTag})"
        docker tag "${registry}/${svc}:${OldTag}" $image
    }

    Write-Host "[PUSH] ${svc}"
    docker push $image
}

Write-Host ""
Write-Host "Done: all images pushed to Harbor with tag ${NewTag}"