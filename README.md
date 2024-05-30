# Super Image Quality Enhancer description  
 Developing a deep learning model utilizing residual dense blocks (RDBs) to enhance image quality by focusing on its luminance (Y) component

# Running the Application and Testing the Models
To test the models, follow these steps:
1. Navigate to the "Application & GUI" Folder: Open the "App.ipynb" file.
2. Install Necessary Libraries: Ensure all required libraries are installed.
3. Run the Application: Execute the notebook, and a web page will automatically open in your browser.
4. Select Model and Image: Choose the model and image you want to enhance. The enhanced result will appear in the left box.
5. Compare Images: Use the "compare" button to view the original image alongside the enhanced version.


# Creating Your Own Model:
1. Navigate to the "Model Creation Code" Folder: Open the "Model Creator.ipynb" file.
2. Install Necessary Libraries: Ensure all required libraries are installed.
3. Adjust Variables: Modify the following variables as needed:
4. Dataset_location: Specify the location of your dataset.
5. ModelName: Set your preferred model name or use the default.
6. Hyperparameters: Adjust or keep the default values:
      - cropped_width = 600
      - cropped_height = 300
      - batch_size = 32
      - seed = 240
      - validation_split = 0.2
      - upscale_factor = 3
      - epochs_number = 100

# Model architecture review:
![v10 keras](https://github.com/AmerZuher/Super-Image-Quality-Enhancer-/assets/80674857/9cb03afe-383f-4c79-86eb-c07565204e68)


# Note
For more explanation, you can go to the pdf file "Resolution Revolution Unleashing AI for Superior Image Quality.pdf" on the main page.

Feel free to experiment with and adjust any settings. The model architecture uses Residual Dense Blocks (RDB), a common structure in image processing models. We used three RDBs and focused on the Y channel from the YUV color space to reduce the computational power needed for training.

Please be aware that the model's performance may vary due to our limited resources. It is recommended to create and test your own model within the app for optimal results.

# Thank you for your time.
