import os
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View
import aiohttp
import random
import urllib.parse
import time
import io
from io import BytesIO
from PIL import Image
import imageio
from typing import Optional, Dict, Any

#Config
DISCORD_BOT_TOKEN = "BOT_TOKEN"

#file size limits
MAX_INPUT_FILE_SIZE_MB = 8
MAX_OUTPUT_FILE_SIZE_MB = 10

#bot setup
# set up the intents we need
intents = discord.Intents.default()
# need this to check guild members for permissions
intents.members = True
# need this to read messages/attachments for the /togif command
intents.message_content = True

# custom bot class
class ImageBot(commands.Bot):
    def __init__(self):
        # init the bot with a prefix (if needed to add a prefix command)
        super().__init__(command_prefix="!", intents=intents)

    async def on_ready(self):
        """confirms the bot is logged in and ready."""
        print(f'logged in as {self.user}')
        # Sync the commands
        try:
            # sync the slash commands to discord
            synced = await self.tree.sync()
            print(f"synced {len(synced)} command/s")
        except Exception as e:
            print(f"failed to sync commands: {e}")

bot = ImageBot()

async def generate_image(prompt: str, model: str = "flux"):
    """Helper function to call the image generation API"""
    # pick a random seed so we get a different image each time
    seed = random.randint(0, 999999)
    # make the prompt safe for a URL
    encoded_prompt = urllib.parse.quote(prompt)
    # build the API URL with all the parameters
    api_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&model={model}&seed={seed}&private=true&safe=true"
    
    # use aiohttp to make the request
    async with aiohttp.ClientSession() as session:
        async with session.get(api_url) as response:
            if response.status == 200:
                # return the raw image dat
                return await response.read()
            else:
                # throw an error if the API call failed
                raise Exception(f"API returned status code {response.status}")

#Utility Views
class RegenerateView(discord.ui.View):
    """A custom view that handles the Regenerate button for image generation."""
    def __init__(self, prompt: str, model: str, message: discord.Message, author_id: int):
        super().__init__(timeout=None)
        # store the prompt and model to use for regeneration
        self.prompt = prompt
        self.model = model
        # store the original message to edit it later
        self.message = message
        # store the author ID so only they can use the button
        self.author_id = author_id
        # flag to prevent multiple regeneration attempts at once
        self.regenerating = False

    @discord.ui.button(label="🔁 Regenerate", style=discord.ButtonStyle.primary)
    async def regenerate(self, interaction: discord.Interaction, button: discord.ui.Button):
        #check if the user clicking is the original command author
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "you can't use this button it belongs to the command author",
                ephemeral=True
            )
            return

        # check if a regeneration is already in progress
        if self.regenerating:
            await interaction.response.send_message("already regenerating, please wait...", ephemeral=True)
            return

        try:
            self.regenerating = True
            # disable the button while we work
            button.disabled = True
            # update the message to show the button is disabled
            await interaction.response.edit_message(view=self)
            
            #send a loading embed
            regen_embed = discord.Embed(
                title="regenerating Image..",
                description="pls wait a few seconds..",
                color=discord.Color.orange()
            )
            # edit the message to show the loading embed
            await self.message.edit(embed=regen_embed, attachments=[], view=self)

            # regenerate the image
            image_data = await generate_image(self.prompt, self.model)
            
            # the final embed for the new image
            embed = discord.Embed(
                title="image generated (regenerated)",
                description=f"**Prompt:** `{self.prompt}`",
                color=discord.Color.green()
            )
            embed.set_image(url="attachment://generated_image.png")

            # re enable the button and reset the flag
            button.disabled = False
            self.regenerating = False
            # edit the message with the new image and re enabled button
            await self.message.edit(
                embed=embed,
                attachments=[discord.File(BytesIO(image_data), filename="generated_image.png")],
                view=self
            )
        except Exception as e:
            # if something goes wrong, re enable the button and show an error
            self.regenerating = False
            button.disabled = False
            error_embed = discord.Embed(
                title="Error",
                description=f"could not regenerate image.\nError: `{str(e)}`",
                color=discord.Color.red()
            )
            await self.message.edit(embed=error_embed, attachments=[], view=self)

#Slash Commands

#/imagine command
@bot.tree.command(name="imagine", description="Generate an image based on your prompt")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.choices(model=[
    app_commands.Choice(name="flux", value="flux"),
    app_commands.Choice(name="flux-pro", value="flux-pro"),
    app_commands.Choice(name="flux-cablyai", value="flux-cablyai")
])
async def imagine(interaction: discord.Interaction, prompt: str, model: app_commands.Choice[str] = None):
    """handles the /imagine slash command"""
    # defer the response so we have time to generate the image
    await interaction.response.defer()
    # get the selected model, default to flux
    selected_model = model.value if model else "flux"

    #permissions check before sending anything
    if interaction.guild:
        perms = interaction.channel.permissions_for(interaction.guild.me)
        # check if the bot has the necessary permissions
        if not perms.send_messages or not perms.embed_links or not perms.attach_files:
            error_msg = " I need the following permissions: `Send Messages`, `Embed Links` and `Attach Files` make sure i have them all."
            await interaction.followup.send(error_msg, ephemeral=True)
            return

    # loading embed
    generating_embed = discord.Embed(
        title="Generating Image..",
        description="this usually takes a few seconds..",
        color=discord.Color.purple()
    )

    try:
        #Send the loading embed
        # send the initial message with the loading embed
        message = await interaction.followup.send(embed=generating_embed)
    except discord.Forbidden:
        # if we cant send the embed/attachment, send a simple error message
        await interaction.followup.send(" I wasnt able to send an embed or attachment here.", ephemeral=True)
        return

    try:
        #generate the image
        start_time = time.time()
        # call the helper function to get the image data
        image_data = await generate_image(prompt, selected_model)
        # calculate how long it took
        time_taken = round(time.time() - start_time, 2)

        # final success embed
        embed = discord.Embed(
            title="Image Generated",
            description=f"**Prompt:** ```{prompt}```",
            color=discord.Color.green()
        )
        embed.add_field(name="Time taken", value=f"```{time_taken} seconds```", inline=False)
        embed.set_image(url="attachment://generated_image.png")

        # create the view with the regenerate button
        view = RegenerateView(prompt, selected_model, message, interaction.user.id)

        # edit the message with the final image and the button
        await message.edit(
            embed=embed,
            attachments=[discord.File(BytesIO(image_data), filename="generated_image.png")],
            view=view
        )

    except Exception as e:
        # if the generation failed show an error
        error_embed = discord.Embed(
            title="Error",
            description=f"error generating image: please try again.\nError: `{str(e)}`",
            color=discord.Color.red()
        )
        # edit the message to show the error
        await message.edit(embed=error_embed, attachments=[], view=None)

# /togif command
@bot.tree.command(name="togif", description="converts an image attachment into a GIF")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.describe(
    image_file="the image file to convert to GIF (PNG, JPG, etc)."
)
async def togif(interaction: discord.Interaction, image_file: discord.Attachment):
    """handles the /togif slash command."""
    # defer the response
    await interaction.response.defer(ephemeral=False)

    # set the duration for each frame
    duration_ms = 100 

    #validate input attachment
    # check if the attachment is actually an image type we can handle
    if not image_file.content_type or not image_file.content_type.startswith(('image/jpeg', 'image/png', 'image/webp')):
        await interaction.followup.send(" please provide a valid image file (PNG, JPG, or WebP).")
        return
    
    # check the file size limit
    if image_file.size > MAX_INPUT_FILE_SIZE_MB * 1024 * 1024:
        await interaction.followup.send(f" the image file is too large. Max allowed is {MAX_INPUT_FILE_SIZE_MB} MB.")
        return

    try:
        #download image
        # read the image data into memory
        image_bytes = await image_file.read()
        img_buffer = io.BytesIO(image_bytes)

        #open image with pillow
        try:
            # open the image using PIL
            img = Image.open(img_buffer)
            # convert to RGBA to handle transparency correctly
            img = img.convert("RGBA")
        except Exception as e:
            await interaction.followup.send(f" could not open the image file. `{e}`")
            return

        #prepare frames for GIF
        # for a static image to GIF, we just use one frame
        frames = [img] 

        output_buffer = io.BytesIO()
        # set up the imageio writer for GIF format
        writer = imageio.get_writer(output_buffer, mode='I', format='GIF', duration=duration_ms / 1000.0, loop=0)
        for frame in frames:
            # add the frame to the writer
            writer.append_data(frame)
        writer.close()
        # reset the buffer position to the start
        output_buffer.seek(0)

        # check file size
        # make sure the final GIF isnt too big
        if output_buffer.getbuffer().nbytes > MAX_OUTPUT_FILE_SIZE_MB * 1024 * 1024:
            await interaction.followup.send(f" The generated GIF is too large ({output_buffer.getbuffer().nbytes / (1024*1024):.2f}MB). Max allowed is {MAX_OUTPUT_FILE_SIZE_MB}MB. Try a smaller input image.")
            return

        # send the GIF
        # create a nice filename
        gif_filename = f"{os.path.splitext(image_file.filename)[0]}_converted.gif"
        # create the discord file object
        discord_file = discord.File(output_buffer, filename=gif_filename)

        # final success embed
        embed = discord.Embed(
            title="Image converted to GIF",
            color=discord.Color.blue()
        )
        embed.set_image(url=f"attachment://{gif_filename}")

        # send the embed and the file
        await interaction.followup.send(embed=embed, file=discord_file)
       # if there is error
    except Exception as e:
        print(f"ERROR in /togif command: {e}")
        # send an error message to the user
        await interaction.followup.send(f"❌ an error occurred during GIF conversion: `{e}`")
	
	
#run bot
if __name__ == "__main__":
    # check if the token is still the placeholder
    if DISCORD_BOT_TOKEN == "BOT_TOKEN":
        print(" re place DISCORD_BOT_TOKEN with your bot token.")
    
    else:
        # run the bot
        bot.run(DISCORD_BOT_TOKEN)
