// Function to parse URL query parameters
function getQueryParameter(name) {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get(name);
}

// Get the image name from the URL query parameter
var imageName = getQueryParameter("imageName");

// Update the image sources with the retrieved image name
var beforeImage = document.getElementById("beforeImage");
var afterImage = document.getElementById("afterImage");
var originalDimensions = document.getElementById("originalDimensions");
var enhancedDimensions = document.getElementById("enhancedDimensions");

if (imageName) {
    // Replace the image sources with the correct paths including the image name
    beforeImage.src = "../../processed Images/" + imageName;
    afterImage.src = "../../processed Images/enhanced_" + imageName;

    // Get the dimensions of the images after they have loaded
    beforeImage.onload = function() {
        originalDimensions.innerText =
            "Original\nResolution: " +
            beforeImage.naturalWidth +
            "x" +
            beforeImage.naturalHeight;
    };

    afterImage.onload = function() {
        enhancedDimensions.innerText =
            "Enhanced\nResolution: " +
            afterImage.naturalWidth +
            "x" +
            afterImage.naturalHeight;
    };
} else {
    // Handle case where imageName is not provided
    console.error("Image name is missing.");
}

// Custom Image Comparison Slider Script
let compare = document.querySelector('#image-compare');
let btn = document.querySelector('#button');
let slider = document.querySelector('#slider');
let img1 = document.querySelector('#image-2');
let isClicked = false;
let mPos = { x: 0, y: 0 };

compare.addEventListener('mousedown', e => isClicked = true);
compare.addEventListener('mouseup', e => isClicked = false);
compare.addEventListener('mousemove', e => {
    mPos.x = e.x;
    mPos.y = e.y;
});

function update() {
    requestAnimationFrame(update);
    if (isClicked) {
        var p = compare.getBoundingClientRect().x;
        var w = compare.getBoundingClientRect().width;

        if (mPos.x > p && mPos.x < w + p) {
            var clip = `inset(0 0 0 ${(mPos.x - p).toFixed(0)}px)`;
            img1.style.setProperty('--clip', clip);
            slider.style.left = (mPos.x - p).toFixed(0) + 'px';
        }
    }
}

update();