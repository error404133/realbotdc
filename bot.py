import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from datetime import datetime, timedelta
import time
from collections import defaultdict
import os

# =========================
# INTENTS
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.voice_states = True
intents.invites = True
intents.moderation = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# VARIABLES
# =========================
log_channels = {}
welcome_channels = {}
welcome_images = {}

# Variables pour l'anti-spam
spam_tracker = defaultdict(list)
warn_count = defaultdict(int)

# Configuration anti-spam
SPAM_THRESHOLD = 5
SPAM_WINDOW = 5

# Variables pour les niveaux vocaux
vocal_xp = defaultdict(int)  # {user_id: xp}
vocal_level = defaultdict(int)  # {user_id: level}
vocal_tracker = defaultdict(float)  # {user_id: temps_entree}
vocal_level_channel = {}  # {guild_id: channel_id}
vocal_level_image = {}  # {guild_id: image_url}


# =========================
# =========================
# RÉINITIALISATION AUTO (30s sans spam)
# =========================
async def reset_warnings():
    """Reset les avertissements après 30 secondes sans spam"""
    while True:
        await asyncio.sleep(30)
        now = time.time()
        for user_id in list(spam_tracker.keys()):
            if not spam_tracker[user_id] or now - max(spam_tracker[user_id]) > 30:
                if user_id in warn_count:
                    warn_count[user_id] = 0
                spam_tracker[user_id] = []


# =========================
# RÉINITIALISATION AUTO APRÈS TIMEOUT
# =========================
async def auto_reset_after_timeout():
    """Vérifie toutes les heures et reset les warns des utilisateurs qui ne sont plus en timeout"""
    while True:
        await asyncio.sleep(3600)  # Vérifie toutes les heures
        now = datetime.utcnow().replace(tzinfo=None)

        for user_id in list(warn_count.keys()):
            if warn_count.get(user_id, 0) >= 3:
                # Chercher le membre dans tous les serveurs
                for guild in bot.guilds:
                    member = guild.get_member(user_id)
                    if member and member.timed_out_until:
                        timeout_end = member.timed_out_until.replace(tzinfo=None)
                        if timeout_end <= now:
                            # Timeout terminé, reset les warns
                            warn_count[user_id] = 0
                            spam_tracker[user_id] = []
                            print(f"✅ Warns reset pour {member.name} (timeout terminé)")
                            break  # Sort de la boucle des guilds
                    # Si le membre n'est pas trouvé, on continue


# =========================
# READY
# =========================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Connecté en tant que {bot.user}")
    print(f"📊 Anti-spam activé : {SPAM_THRESHOLD} messages en {SPAM_WINDOW} secondes")
    bot.loop.create_task(reset_warnings())
    bot.loop.create_task(auto_reset_after_timeout())


# =========================
# FONCTION D'ENVOI DE LOGS
# =========================
async def send_log(guild, log_type, embed):
    if guild.id not in log_channels:
        return

    channel_id = log_channels[guild.id].get(log_type)
    if not channel_id:
        return

    channel = guild.get_channel(channel_id)
    if channel:
        await channel.send(embed=embed)


# =========================
# BIENVENUE
# =========================
@bot.event
async def on_member_join(member):
    channel_id = welcome_channels.get(member.guild.id)
    if not channel_id:
        return

    channel = member.guild.get_channel(channel_id)
    if not channel:
        return

    embed = discord.Embed(
        title="✨🌸 WELCOME TO THE SERVER 🌸✨",
        description=(
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👋 Bienvenue {member.mention} !\n\n"
            f"🔥 Tu viens de rejoindre {member.guild.name}\n"
            f"💜 On espère que tu vas kiffer ici\n\n"
            f"🎮 Amuse-toi, parle, fais des rencontres\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=0xFFFFFF
    )

    embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
    embed.set_footer(text=f"ID: {member.id} • Bienvenue sur {member.guild.name}")

    image_url = welcome_images.get(member.guild.id)
    if image_url:
        embed.set_image(url=image_url)

    await channel.send(embed=embed)


# =========================
# SYSTÈME DE NIVEAUX VOCAUX
# =========================

def get_xp_for_next_level(level: int) -> int:
    """Calcule l'XP nécessaire pour le prochain niveau (progression de 20 à chaque niveau)"""
    # Niveau 1 -> 2 : 30 XP
    # Niveau 2 -> 3 : 50 XP
    # Niveau 3 -> 4 : 70 XP
    # etc.
    if level == 0:
        return 30
    return 30 + (level - 1) * 20


def get_level_from_xp(xp: int) -> int:
    """Calcule le niveau à partir de l'XP"""
    level = 1
    while True:
        needed = get_xp_for_next_level(level)
        if xp < needed:
            break
        xp -= needed
        level += 1
    return level


def get_xp_progress(xp: int, level: int) -> tuple:
    """Retourne (xp_actuel, xp_necessaire, progression_en_pourcentage)"""
    if level == 1:
        xp_current = xp
        xp_needed = 30
    else:
        xp_current = xp
        xp_needed = get_xp_for_next_level(level)

    progress = min(100, int((xp_current / xp_needed) * 100))
    return xp_current, xp_needed, progress


@bot.event
async def on_voice_state_update(member, before, after):
    # Gagner de l'XP en vocal
    now = time.time()

    # L'utilisateur REJOINT un salon vocal
    if before.channel is None and after.channel is not None:
        vocal_tracker[member.id] = now
        print(f"🎙️ {member.name} a rejoint le vocal - début du chrono")

    # L'utilisateur QUITTE un salon vocal
    elif before.channel is not None and after.channel is None:
        if member.id in vocal_tracker:
            time_spent = now - vocal_tracker[member.id]
            minutes_spent = time_spent / 60

            if minutes_spent >= 1:  # Minimum 1 minute pour gagner de l'XP
                xp_gained = int(minutes_spent)  # 1 XP par minute
                vocal_xp[member.id] = vocal_xp.get(member.id, 0) + xp_gained

                # Vérifier les changements de niveau
                old_level = vocal_level.get(member.id, 1)
                new_level = get_level_from_xp(vocal_xp[member.id])

                if new_level > old_level:
                    vocal_level[member.id] = new_level
                    await send_level_up_message(member, old_level, new_level)  # ← Appel de la fonction externe

                print(f"🎙️ {member.name} a gagné {xp_gained} XP (total: {vocal_xp[member.id]})")

            del vocal_tracker[member.id]

    # L'utilisateur CHANGE de salon vocal
    elif before.channel is not None and after.channel is not None and before.channel != after.channel:
        # Réinitialiser le timer
        if member.id in vocal_tracker:
            time_spent = now - vocal_tracker[member.id]
            minutes_spent = time_spent / 60

            if minutes_spent >= 1:
                xp_gained = int(minutes_spent)
                vocal_xp[member.id] = vocal_xp.get(member.id, 0) + xp_gained

                old_level = vocal_level.get(member.id, 1)
                new_level = get_level_from_xp(vocal_xp[member.id])

                if new_level > old_level:
                    vocal_level[member.id] = new_level
                    await send_level_up_message(member, old_level, new_level)  # ← Appel de la fonction externe

            # Redémarrer le chrono pour le nouveau salon
            vocal_tracker[member.id] = now


async def send_level_up_message(member, old_level, new_level):
    """Envoie un message stylisé quand un membre monte de niveau avec ping"""
    channel_id = vocal_level_channel.get(member.guild.id)
    if not channel_id:
        return

    channel = member.guild.get_channel(channel_id)
    if not channel:
        return

    # Récupérer l'image personnalisée
    image_url = vocal_level_image.get(member.guild.id)

    # Barre de progression stylisée
    stars = "⭐" * min(new_level // 5, 10)

    embed = discord.Embed(
        title="✨🌸 **NIVEAU SUPÉRIEUR !** 🌸✨",
        description=(
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👋 **{member.mention}**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎯 **Niveau {old_level}** → **Niveau {new_level}**\n"
            f"{stars}\n\n"
            f"📊 **Prochain niveau :** `{get_xp_for_next_level(new_level)} XP`\n"
            f"💜 **Continue comme ça, tu gères !**\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=0xFFD700,  # Or
        timestamp=datetime.utcnow()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    if image_url:
        embed.set_image(url=image_url)
    embed.set_footer(text="🎙️ Plus tu parles, plus tu montes !")

    # Ping avec un message d'accompagnement
    await channel.send(
        content=f"🎉 **BRAVO** {member.mention} ! Tu passes au **niveau {new_level}** ! 🎉",
        embed=embed
    )

async def check_level_rewards(member, new_level):
    """Donne des récompenses automatiques selon le niveau"""

    # Définir les récompenses par niveau
    rewards = {
        5: "🎖️ Membre Actif",
        10: "⭐ Vétéran",
        25: "🔥 Légende Vocale",
        50: "👑 Maître du Vocal",
        100: "💎 Dieu du Vocal"
    }

    if new_level in rewards:
        role_name = rewards[new_level]
        role = discord.utils.get(member.guild.roles, name=role_name)

        # Si le rôle n'existe pas, le créer
        if not role:
            role = await member.guild.create_role(name=role_name, reason=f"Récompense niveau {new_level}")

        await member.add_roles(role)

        # Envoyer un message spécial
        channel_id = vocal_level_channel.get(member.guild.id)
        if channel_id:
            channel = member.guild.get_channel(channel_id)
            if channel:
                embed = discord.Embed(
                    title="🎁 **RÉCOMPENSE DÉBLOCKÉE !** 🎁",
                    description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"     👤 {member.mention}\n"
                                f"     🏆 **Niveau {new_level} atteint !**\n"
                                f"     🎭 **Rôle obtenu :** {role.mention}\n"
                                f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                    color=discord.Color.gold()
                )
                await channel.send(embed=embed)

# =========================
# ANTI-SPAM
# =========================
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = message.author.id
    now = time.time()

    # Nettoyer les anciens timestamps
    spam_tracker[user_id] = [t for t in spam_tracker[user_id] if now - t < SPAM_WINDOW]
    spam_tracker[user_id].append(now)
    msg_count = len(spam_tracker[user_id])

    # Détection spam
    if msg_count >= SPAM_THRESHOLD:
        try:
            await message.delete()
        except:
            pass

        current_warns = warn_count.get(user_id, 0)

        if current_warns == 0:
            warn_count[user_id] = 1
            warn_msg = await message.channel.send(
                f"⚠️ **{message.author.mention}** ⚠️\n"
                f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"     🚫 **Attention !** Ne spam pas stp.\n"
                f"     ➜ Ralentis *(1/3 avertissements)*"
            )
            await asyncio.sleep(5)
            try:
                await warn_msg.delete()
            except:
                pass

        elif current_warns == 1:
            warn_count[user_id] = 2
            warn_msg = await message.channel.send(
                f"⚠️ **{message.author.mention}** ⚠️\n"
                f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"     🚫 **DERNIER AVERTISSEMENT !**\n"
                f"     ➜ Prochain spam = timeout 1 jour *(2/3)*"
            )
            await asyncio.sleep(5)
            try:
                await warn_msg.delete()
            except:
                pass

        elif current_warns >= 2:
            warn_count[user_id] = 3

            timeout_embed = discord.Embed(
                title="⏰ **TIMEOUT - SPAM**",
                description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"     🔨 **{message.author}** a été timeout\n"
                            f"     📝 **Raison :** Spam excessif\n"
                            f"     ⏱️ **Durée :** 1 jour\n"
                            f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                color=0xFF6464,
                timestamp=datetime.utcnow()
            )
            timeout_embed.set_thumbnail(url=message.author.display_avatar.url)
            timeout_embed.set_footer(text=f"ID: {message.author.id} • Système Anti-Spam")

            try:
                await message.author.timeout(
                    discord.utils.utcnow() + timedelta(days=1),
                    reason="Spam excessif"
                )
                await message.channel.send(embed=timeout_embed)

                log_embed = discord.Embed(
                    title="⏰ TIMEOUT AUTOMATIQUE",
                    description=f"**Utilisateur :** {message.author.mention}\n"
                                f"**Raison :** Spam excessif\n"
                                f"**Durée :** 1 jour\n"
                                f"**Messages en 5s :** {msg_count}",
                    color=discord.Color.yellow(),
                    timestamp=datetime.utcnow()
                )
                log_embed.set_thumbnail(url=message.author.display_avatar.url)
                await send_log(message.guild, "moderation", log_embed)

                spam_tracker[user_id] = []
                warn_count[user_id] = 0

            except discord.Forbidden:
                await message.channel.send(f"❌ Impossible de timeout {message.author.mention} - Permissions manquantes")
            except Exception as e:
                await message.channel.send(f"❌ Erreur : {e}")

        spam_tracker[user_id] = [t for t in spam_tracker[user_id] if now - t < 0.5]
        return

    await bot.process_commands(message)


# =========================
# RÉINITIALISATION AUTO APRÈS TIMEOUT
# =========================
async def auto_reset_after_timeout():
    """Vérifie toutes les heures et reset les warns des utilisateurs qui ne sont plus en timeout"""
    while True:
        await asyncio.sleep(3600)  # Vérifie toutes les heures
        now = datetime.utcnow().replace(tzinfo=None)

        for user_id in list(warn_count.keys()):
            if warn_count.get(user_id, 0) >= 3:
                # Chercher le membre dans tous les serveurs
                for guild in bot.guilds:
                    member = guild.get_member(user_id)
                    if member and member.timed_out_until:
                        timeout_end = member.timed_out_until.replace(tzinfo=None)
                        if timeout_end <= now:
                            # Timeout terminé, reset les warns
                            warn_count[user_id] = 0
                            spam_tracker[user_id] = []
                            print(f"✅ Warns reset pour {member.name} (timeout terminé)")
                        break

# =========================
# LOG MESSAGE SUPPRIMÉ
# =========================
@bot.event
async def on_message_delete(message):
    if message.author.bot:
        return

    # Petite attente pour permettre à l'audit log d'enregistrer
    await asyncio.sleep(1)

    # Qui a supprimé le message ?
    deleter = None

    # Vérifier l'audit log pour voir qui a supprimé
    async for entry in message.guild.audit_logs(limit=5, action=discord.AuditLogAction.message_delete):
        if entry.target.id == message.author.id:
            # Vérifier que l'entrée est récente (moins de 2 secondes)
            time_diff = (datetime.utcnow().replace(tzinfo=None) - entry.created_at).total_seconds()
            if time_diff < 3:
                deleter = entry.user
                break

    # Créer l'embed
    if deleter and deleter.id != message.author.id:
        title = "🗑️ MESSAGE SUPPRIMÉ (MODÉRATION)"
        deleted_by = f"**Supprimé par :** {deleter.mention}"
    else:
        title = "🗑️ MESSAGE SUPPRIMÉ (AUTEUR)"
        deleted_by = f"**Supprimé par :** {message.author.mention} (auteur)"

    embed = discord.Embed(
        title=title,
        description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"     **Auteur :** {message.author.mention}\n"
                    f"     **Salon :** {message.channel.mention}\n"
                    f"     **Contenu :** {message.content[:1000] if message.content else '*Aucun contenu*'}\n"
                    f"{deleted_by}\n"
                    f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )
    embed.set_thumbnail(url=message.author.display_avatar.url)

    await send_log(message.guild, "messages", embed)


# =========================
# LOG MESSAGE MODIFIÉ (VERSION SIMPLIFIÉE)
# =========================
@bot.event
async def on_message_edit(before, after):
    # Ignorer les bots et les messages sans changement
    if before.author.bot or before.content == after.content:
        return

    # Créer l'embed
    embed = discord.Embed(
        title="✏️ Message modifié",
        description=f"**Auteur :** {before.author.mention}\n"
                    f"**Salon :** {before.channel.mention}\n\n"
                    f"**Avant :**\n```{before.content[:500] if before.content else '*Vide*'}```\n"
                    f"**Après :**\n```{after.content[:500] if after.content else '*Vide*'}```",
        color=discord.Color.orange(),
        timestamp=datetime.utcnow()
    )
    embed.set_thumbnail(url=before.author.display_avatar.url)
    embed.set_footer(text=f"ID: {before.author.id}")

    await send_log(before.guild, "messages", embed)


# =========================
# BAN LOG
# =========================
@bot.event
async def on_member_ban(guild, user):
    await asyncio.sleep(1)

    embed = discord.Embed(
        title="🔨 BAN",
        color=discord.Color.dark_red(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Utilisateur banni", value=f"{user} ({user.mention})", inline=True)
    embed.set_thumbnail(url=user.display_avatar.url)

    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
        if entry.target.id == user.id:
            embed.add_field(name="Banni par", value=f"{entry.user} ({entry.user.mention})", inline=True)
            if entry.reason:
                embed.add_field(name="Raison", value=entry.reason, inline=False)
            break

    await send_log(guild, "moderation", embed)


# =========================
# KICK LOG
# =========================
@bot.event
async def on_member_remove(member):
    await asyncio.sleep(1)

    is_kick = False
    kicker = None
    reason = None

    async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
        if entry.target.id == member.id:
            is_kick = True
            kicker = entry.user
            reason = entry.reason
            break

    if is_kick:
        embed = discord.Embed(
            title="👢 KICK",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Utilisateur kick", value=f"{member} ({member.mention})", inline=True)
        embed.add_field(name="Kick par", value=f"{kicker} ({kicker.mention})", inline=True)
        if reason:
            embed.add_field(name="Raison", value=reason, inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        await send_log(member.guild, "moderation", embed)


# =========================
# MEMBER UPDATE (TIMEOUTS + ROLES)
# =========================
@bot.event
async def on_member_update(before, after):
    # TIMEOUTS
    if before.timed_out_until != after.timed_out_until:
        await asyncio.sleep(1)

        embed = discord.Embed(
            title="⏰ TIMEOUT" if after.timed_out_until else "✅ FIN DU TIMEOUT",
            color=discord.Color.yellow() if after.timed_out_until else discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Utilisateur", value=f"{after} ({after.mention})", inline=True)

        if after.timed_out_until:
            duration = (after.timed_out_until - datetime.utcnow().replace(tzinfo=None)).total_seconds() / 3600
            embed.add_field(name="Durée", value=f"{int(duration)} heures", inline=True)

            try:
                async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_update):
                    if entry.target.id == after.id:
                        embed.add_field(name="Modérateur", value=f"{entry.user} ({entry.user.mention})", inline=True)
                        if entry.reason:
                            embed.add_field(name="Raison", value=entry.reason, inline=False)
                        break
            except discord.NotFound:
                pass

        embed.set_thumbnail(url=after.display_avatar.url)
        await send_log(after.guild, "moderation", embed)

    # RÔLES AJOUTÉS/RETIRÉS
    before_roles = set(before.roles)
    after_roles = set(after.roles)

    roles_ajoutes = after_roles - before_roles
    roles_retires = before_roles - after_roles

    for role in roles_ajoutes:
        if role.name == "@everyone":
            continue

        await asyncio.sleep(1)

        giver = None
        try:
            async for entry in after.guild.audit_logs(limit=3, action=discord.AuditLogAction.member_role_update):
                if entry.target.id == after.id:
                    giver = entry.user
                    break
        except discord.NotFound:
            pass

        embed = discord.Embed(
            title="✅ **RÔLE AJOUTÉ**",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     **Membre :** {after.mention}\n"
                        f"     **Rôle ajouté :** {role.mention}\n"
                        f"     **Par :** {giver.mention if giver else 'Inconnu'}\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        embed.set_thumbnail(url=after.display_avatar.url)
        embed.set_footer(text=f"ID: {after.id}")
        await send_log(after.guild, "moderation", embed)

    for role in roles_retires:
        if role.name == "@everyone":
            continue

        await asyncio.sleep(1)

        taker = None
        try:
            async for entry in after.guild.audit_logs(limit=3, action=discord.AuditLogAction.member_role_update):
                if entry.target.id == after.id:
                    taker = entry.user
                    break
        except discord.NotFound:
            pass

        embed = discord.Embed(
            title="❌ **RÔLE RETIRÉ**",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     **Membre :** {after.mention}\n"
                        f"     **Rôle retiré :** `{role.name}`\n"
                        f"     **Par :** {taker.mention if taker else 'Inconnu'}\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.set_thumbnail(url=after.display_avatar.url)
        embed.set_footer(text=f"ID: {after.id}")
        await send_log(after.guild, "moderation", embed)


# =========================
# VOICE STATE UPDATE
# =========================
@bot.event
async def on_voice_state_update(member, before, after):
    # DÉPLACEMENT
    if before.channel is not None and after.channel is not None and before.channel != after.channel:
        embed = discord.Embed(
            title="🔄 DÉPLACEMENT VOCAL",
            description=f"**Membre :** {member.mention}\n"
                        f"**De :** {before.channel.mention}\n"
                        f"**Vers :** {after.channel.mention}",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"ID: {member.id}")
        await send_log(member.guild, "voice", embed)

    elif before.channel is None and after.channel is not None:
        embed = discord.Embed(
            title="🎧 REJOINT VOCAL",
            description=f"{member.mention} a rejoint {after.channel.mention}",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await send_log(member.guild, "voice", embed)

    elif before.channel is not None and after.channel is None:
        embed = discord.Embed(
            title="🔇 QUITTÉ VOCAL",
            description=f"{member.mention} a quitté {before.channel.mention}",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await send_log(member.guild, "voice", embed)

    if before.self_mute != after.self_mute:
        embed = discord.Embed(
            title="🎤 MICRO MUTÉ" if after.self_mute else "🎤 MICRO DÉMUTÉ",
            description=f"{member.mention} a {'muté' if after.self_mute else 'démuté'} son micro",
            color=discord.Color.dark_grey() if after.self_mute else discord.Color.light_grey(),
            timestamp=datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await send_log(member.guild, "voice", embed)

    if before.self_deaf != after.self_deaf:
        embed = discord.Embed(
            title="🔇 SOURDINE ACTIVÉE" if after.self_deaf else "🔊 SOURDINE DÉSACTIVÉE",
            description=f"{member.mention} a {'activé' if after.self_deaf else 'désactivé'} la sourdine",
            color=discord.Color.dark_red() if after.self_deaf else discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await send_log(member.guild, "voice", embed)


# =========================
# INVITE CREATE
# =========================
@bot.event
async def on_invite_create(invite):
    embed = discord.Embed(
        title="🔗 INVITATION CRÉÉE",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Créateur", value=f"{invite.inviter} ({invite.inviter.mention})", inline=True)
    embed.add_field(name="Salon", value=invite.channel.mention, inline=True)
    embed.add_field(name="Code", value=invite.code, inline=True)
    embed.add_field(name="Expiration", value=f"{invite.max_age // 60} minutes" if invite.max_age > 0 else "Jamais", inline=True)
    embed.add_field(name="Utilisations max", value=invite.max_uses if invite.max_uses > 0 else "Illimité", inline=True)
    embed.set_footer(text=f"ID créateur: {invite.inviter.id}")
    await send_log(invite.guild, "invites", embed)


# =========================
# CHANNEL CREATE/DELETE/UPDATE
# =========================
@bot.event
async def on_guild_channel_create(channel):
    await asyncio.sleep(1)

    creator = None
    async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
        if entry.target.id == channel.id:
            creator = entry.user
            break

    channel_type = "📝 Texte" if isinstance(channel, discord.TextChannel) else "🔊 Vocal" if isinstance(channel, discord.VoiceChannel) else "🏷️ Catégorie"

    embed = discord.Embed(
        title="➕ **SALON CRÉÉ**",
        description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"     **Nom :** {channel.mention}\n"
                    f"     **Type :** {channel_type}\n"
                    f"     **Créé par :** {creator.mention if creator else 'Inconnu'}\n"
                    f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )
    embed.set_footer(text=f"ID: {channel.id}")
    await send_log(channel.guild, "moderation", embed)


@bot.event
async def on_guild_channel_delete(channel):
    await asyncio.sleep(1)

    deleter = None
    async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
        if entry.target.id == channel.id:
            deleter = entry.user
            break

    channel_type = "📝 Texte" if isinstance(channel, discord.TextChannel) else "🔊 Vocal" if isinstance(channel, discord.VoiceChannel) else "🏷️ Catégorie"

    embed = discord.Embed(
        title="➖ **SALON SUPPRIMÉ**",
        description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"     **Nom :** #{channel.name}\n"
                    f"     **Type :** {channel_type}\n"
                    f"     **Supprimé par :** {deleter.mention if deleter else 'Inconnu'}\n"
                    f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )
    embed.set_footer(text=f"ID: {channel.id}")
    await send_log(channel.guild, "moderation", embed)


@bot.event
async def on_guild_channel_update(before, after):
    if before.name != after.name:
        await asyncio.sleep(1)

        modifier = None
        async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_update):
            if entry.target.id == after.id:
                modifier = entry.user
                break

        channel_type = "📝 Texte" if isinstance(after, discord.TextChannel) else "🔊 Vocal" if isinstance(after, discord.VoiceChannel) else "🏷️ Catégorie"

        embed = discord.Embed(
            title="✏️ **SALON MODIFIÉ**",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     **Type :** {channel_type}\n"
                        f"     **Ancien nom :** #{before.name}\n"
                        f"     **Nouveau nom :** {after.mention}\n"
                        f"     **Modifié par :** {modifier.mention if modifier else 'Inconnu'}\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text=f"ID: {after.id}")
        await send_log(after.guild, "moderation", embed)


# =========================
# ROLE CREATE/DELETE/UPDATE
# =========================
@bot.event
async def on_guild_role_create(role):
    """Log quand un rôle est créé"""
    await asyncio.sleep(1)

    try:
        if not role.guild:
            return

        creator = None
        async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_create):
            if entry.target.id == role.id:
                creator = entry.user
                break

        embed = discord.Embed(
            title="🎭 **RÔLE CRÉÉ**",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     **Nom :** {role.mention}\n"
                        f"     **Couleur :** `{str(role.color)}`\n"
                        f"     **Créé par :** {creator.mention if creator else 'Inconnu'}\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text=f"ID: {role.id}")
        await send_log(role.guild, "moderation", embed)

    except discord.NotFound:
        pass
    except Exception as e:
        print(f"Erreur dans on_guild_role_create: {e}")


@bot.event
async def on_guild_role_delete(role):
    """Log quand un rôle est supprimé"""
    await asyncio.sleep(1)

    try:
        # Vérifier que le serveur existe toujours
        if not role.guild:
            return

        deleter = None
        async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
            if entry.target.id == role.id:
                deleter = entry.user
                break

        embed = discord.Embed(
            title="🗑️ **RÔLE SUPPRIMÉ**",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     **Nom :** `{role.name}`\n"
                        f"     **Couleur :** `{str(role.color)}`\n"
                        f"     **Supprimé par :** {deleter.mention if deleter else 'Inconnu'}\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text=f"ID: {role.id}")
        await send_log(role.guild, "moderation", embed)

    except discord.NotFound:
        # Le serveur n'existe plus, on ignore
        pass
    except Exception as e:
        print(f"Erreur dans on_guild_role_delete: {e}")


@bot.event
async def on_guild_role_update(before, after):
    """Log quand un rôle est modifié"""
    await asyncio.sleep(1)

    try:
        if not after.guild:
            return

        modifier = None
        async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_update):
            if entry.target.id == after.id:
                modifier = entry.user
                break

        changes = []

        if before.name != after.name:
            changes.append(f"**Nom :** `{before.name}` → `{after.name}`")

        if before.color != after.color:
            changes.append(f"**Couleur :** `{before.color}` → `{after.color}`")

        if before.mentionable != after.mentionable:
            changes.append(f"**Mentionnable :** `{before.mentionable}` → `{after.mentionable}`")

        if before.hoist != after.hoist:
            changes.append(f"**Affiché séparément :** `{before.hoist}` → `{after.hoist}`")

        if changes:
            embed = discord.Embed(
                title="✏️ **RÔLE MODIFIÉ**",
                description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"     **Rôle :** {after.mention}\n"
                            f"     **Modifié par :** {modifier.mention if modifier else 'Inconnu'}\n"
                            f"     **Changements :**\n" + "\n".join([f"       • {c}" for c in changes]) + f"\n"
                                                                                                          f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                color=discord.Color.orange(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text=f"ID: {after.id}")
            await send_log(after.guild, "moderation", embed)

    except discord.NotFound:
        pass
    except Exception as e:
        print(f"Erreur dans on_guild_role_update: {e}")

# =========================
# COMMANDES DE BIENVENUE
# =========================

@bot.tree.command(name="setwelcome")
async def setwelcome(interaction: discord.Interaction, channel: discord.TextChannel):
    """Définit le salon de bienvenue"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Permission administrateur requise.", ephemeral=True)
        return

    welcome_channels[interaction.guild.id] = channel.id
    await interaction.response.send_message(f"✅ Salon de bienvenue : {channel.mention}")


@bot.tree.command(name="removewelcome")
async def removewelcome(interaction: discord.Interaction):
    """Désactive la bienvenue"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Permission administrateur requise.", ephemeral=True)
        return

    if interaction.guild.id in welcome_channels:
        del welcome_channels[interaction.guild.id]
    await interaction.response.send_message("❌ Bienvenue désactivée.")


@bot.tree.command(name="setwelcomeimage")
async def setwelcomeimage(interaction: discord.Interaction, url: str):
    """Définit l'image du message de bienvenue"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Permission administrateur requise.", ephemeral=True)
        return

    welcome_images[interaction.guild.id] = url
    await interaction.response.send_message(f"✅ Image de bienvenue définie !")


@bot.tree.command(name="removewelcomeimage")
async def removewelcomeimage(interaction: discord.Interaction):
    """Supprime l'image du message de bienvenue"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Permission administrateur requise.", ephemeral=True)
        return

    if interaction.guild.id in welcome_images:
        del welcome_images[interaction.guild.id]
    await interaction.response.send_message("❌ Image de bienvenue supprimée.")

# =========================
# COMMANDES SETLOG
# =========================

@bot.tree.command(name="setlog_moderation")
async def setlog_moderation(interaction: discord.Interaction, channel: discord.TextChannel):
    """Définit le salon pour les logs de modération (bans, kicks, timeouts)"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Permission admin requise.", ephemeral=True)
        return

    if interaction.guild.id not in log_channels:
        log_channels[interaction.guild.id] = {}
    log_channels[interaction.guild.id]["moderation"] = channel.id
    await interaction.response.send_message(f"✅ Logs modération : {channel.mention}")


@bot.tree.command(name="setlog_messages")
async def setlog_messages(interaction: discord.Interaction, channel: discord.TextChannel):
    """Définit le salon pour les logs de messages (suppressions, modifications)"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Permission admin requise.", ephemeral=True)
        return

    if interaction.guild.id not in log_channels:
        log_channels[interaction.guild.id] = {}
    log_channels[interaction.guild.id]["messages"] = channel.id
    await interaction.response.send_message(f"✅ Logs messages : {channel.mention}")


@bot.tree.command(name="setlog_voice")
async def setlog_voice(interaction: discord.Interaction, channel: discord.TextChannel):
    """Définit le salon pour les logs vocaux (join/leave/mute)"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Permission admin requise.", ephemeral=True)
        return

    if interaction.guild.id not in log_channels:
        log_channels[interaction.guild.id] = {}
    log_channels[interaction.guild.id]["voice"] = channel.id
    await interaction.response.send_message(f"✅ Logs vocaux : {channel.mention}")


@bot.tree.command(name="setlog_invites")
async def setlog_invites(interaction: discord.Interaction, channel: discord.TextChannel):
    """Définit le salon pour les logs d'invitations"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Permission admin requise.", ephemeral=True)
        return

    if interaction.guild.id not in log_channels:
        log_channels[interaction.guild.id] = {}
    log_channels[interaction.guild.id]["invites"] = channel.id
    await interaction.response.send_message(f"✅ Logs invitations : {channel.mention}")


# =========================
# COMMANDES - BIEN DÉSINDENTÉES (SANS ESPACES DEVANT)
# =========================

@bot.tree.command(name="log_config")
async def log_config(interaction: discord.Interaction):
    embed = discord.Embed(title="📋 CONFIGURATION", color=discord.Color.blue())

    if interaction.guild.id in welcome_channels:
        channel = interaction.guild.get_channel(welcome_channels[interaction.guild.id])
        embed.add_field(name="✨ Bienvenue", value=channel.mention if channel else "❌", inline=False)

    if interaction.guild.id in welcome_images:
        embed.add_field(name="🖼️ Image", value="[Clique ici](" + welcome_images[interaction.guild.id] + ")", inline=False)

    if interaction.guild.id in log_channels:
        logs_text = ""
        for log_type, channel_id in log_channels[interaction.guild.id].items():
            channel = interaction.guild.get_channel(channel_id)
            logs_text += f"• {log_type}: {channel.mention if channel else '❌'}\n"
        embed.add_field(name="📊 Logs", value=logs_text or "*Aucun*", inline=False)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="warnings")
async def check_warnings(interaction: discord.Interaction, member: discord.Member = None):
    """Voir les avertissements d'un membre"""
    if not interaction.user.guild_permissions.moderate_members:
        await interaction.response.send_message("❌ Permission modération requise.", ephemeral=True)
        return

    target = member or interaction.user
    warns = warn_count.get(target.id, 0)

    embed = discord.Embed(
        title="⚠️ **SYSTÈME D'AVERTISSEMENT**",
        description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"     👤 **Membre :** {target.mention}\n"
                    f"     📊 **Avertissements :** {warns}/3\n"
                    f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        color=discord.Color.orange() if warns > 0 else discord.Color.green(),
        timestamp=datetime.utcnow()
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="reset_warnings")
async def reset_warnings_cmd(interaction: discord.Interaction, member: discord.Member):
    """Reset les avertissements d'un membre (admin uniquement)"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Permission administrateur requise.", ephemeral=True)
        return

    warn_count[member.id] = 0
    spam_tracker[member.id] = []

    embed = discord.Embed(
        title="✅ **AVERTISSEMENTS RÉINITIALISÉS**",
        description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"     👤 **Membre :** {member.mention}\n"
                    f"     📊 **Nouveau statut :** 0/3 avertissements\n"
                    f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="warn")
@app_commands.describe(member="Le membre à avertir", reason="La raison de l'avertissement")
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "Aucune raison fournie"):
    """Donne un avertissement à un membre (modérateur)"""

    if not interaction.user.guild_permissions.moderate_members:
        await interaction.response.send_message("❌ Permission 'Gérer les membres' requise.", ephemeral=True)
        return

    if member == interaction.user:
        await interaction.response.send_message("❌ Tu ne peux pas te warn toi-même.", ephemeral=True)
        return

    if member.guild_permissions.administrator:
        await interaction.response.send_message("❌ Tu ne peux pas warn un administrateur.", ephemeral=True)
        return

    current_warns = warn_count.get(member.id, 0)
    new_warns = current_warns + 1

    if new_warns >= 3:
        warn_count[member.id] = 3

        try:
            await member.timeout(
                discord.utils.utcnow() + timedelta(days=1),
                reason=f"3 avertissements - {reason}"
            )

            timeout_embed = discord.Embed(
                title="⏰ **TIMEOUT - 3 AVERTISSEMENTS**",
                description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"     🔨 **{member}** a été timeout\n"
                            f"     📝 **Raison :** {reason}\n"
                            f"     ⏱️ **Durée :** 1 jour\n"
                            f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                color=0xFF6464,
                timestamp=datetime.utcnow()
            )
            timeout_embed.set_thumbnail(url=member.display_avatar.url)
            await interaction.response.send_message(embed=timeout_embed)

            log_embed = discord.Embed(
                title="⚠️ WARN + TIMEOUT",
                description=f"**Membre :** {member.mention}\n"
                            f"**Modérateur :** {interaction.user.mention}\n"
                            f"**Raison :** {reason}\n"
                            f"**Statut :** Timeout 1j (3/3 warns)",
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            await send_log(interaction.guild, "moderation", log_embed)

        except Exception as e:
            await interaction.response.send_message(f"❌ Erreur : {e}", ephemeral=True)

    else:
        warn_count[member.id] = new_warns

        warn_embed = discord.Embed(
            title="⚠️ **AVERTISSEMENT**",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     👤 **Membre :** {member.mention}\n"
                        f"     📝 **Raison :** {reason}\n"
                        f"     📊 **Avertissements :** {new_warns}/3\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        warn_embed.set_thumbnail(url=member.display_avatar.url)
        warn_embed.set_footer(text=f"Modérateur : {interaction.user}")
        await interaction.response.send_message(embed=warn_embed)

        log_embed = discord.Embed(
            title="⚠️ AVERTISSEMENT DONNÉ",
            description=f"**Membre :** {member.mention}\n"
                        f"**Modérateur :** {interaction.user.mention}\n"
                        f"**Raison :** {reason}\n"
                        f"**Avertissements :** {new_warns}/3",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        await send_log(interaction.guild, "moderation", log_embed)


@bot.tree.command(name="set_spam_threshold")
@app_commands.describe(messages="Nombre de messages", seconds="Période en secondes")
async def set_spam_threshold(interaction: discord.Interaction, messages: int, seconds: int):
    """Définit la sensibilité anti-spam (admin uniquement)"""
    global SPAM_THRESHOLD, SPAM_WINDOW

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Permission administrateur requise.", ephemeral=True)
        return

    if messages < 3:
        await interaction.response.send_message("❌ Minimum 3 messages.", ephemeral=True)
        return

    if seconds < 2:
        await interaction.response.send_message("❌ Minimum 2 secondes.", ephemeral=True)
        return

    SPAM_THRESHOLD = messages
    SPAM_WINDOW = seconds

    await interaction.response.send_message(
        f"✅ Configuration anti-spam mise à jour :\n"
        f"➜ {messages} messages en {seconds} secondes = avertissement\n"
        f"➜ 3 avertissements = timeout 1 jour"
    )


@bot.tree.command(name="clear")
@app_commands.describe(amount="Nombre de messages à supprimer (max 100)")
async def clear(interaction: discord.Interaction, amount: int):
    """Supprime un certain nombre de messages dans le salon"""

    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("❌ Permission **Gérer les messages** requise.", ephemeral=True)
        return

    if amount > 100:
        amount = 100
    if amount < 1:
        await interaction.response.send_message("❌ Minimum 1 message.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    try:
        deleted = await interaction.channel.purge(limit=amount)

        embed = discord.Embed(
            title="🗑️ **CLEAR**",
            description=f"✅ {len(deleted)} messages supprimés par {interaction.user.mention}",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        log_embed = discord.Embed(
            title="🧹 CLEAR EXÉCUTÉ",
            description=f"**Modérateur :** {interaction.user.mention}\n"
                        f"**Salon :** {interaction.channel.mention}\n"
                        f"**Messages supprimés :** {len(deleted)}",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        await send_log(interaction.guild, "moderation", log_embed)

    except discord.Forbidden:
        await interaction.followup.send("❌ Je n'ai pas la permission de supprimer des messages.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Erreur : {e}", ephemeral=True)


@bot.command(name="ping")
async def ping(ctx):
    """!ping - Test si le bot répond"""
    await ctx.send("🏓 Pong!")


@bot.command(name="clear_prefix")
async def clear_prefix(ctx, amount: int = 10):
    """!clear_prefix 50 - Supprime des messages (alternative)"""
    if not ctx.author.guild_permissions.manage_messages:
        await ctx.send("❌ Permission requise.")
        return

    if amount > 100:
        amount = 100
    if amount < 1:
        await ctx.send("❌ Minimum 1 message.")
        return

    deleted = await ctx.channel.purge(limit=amount)
    await ctx.send(f"✅ {len(deleted)} messages supprimés", delete_after=3)


# =========================
# COMMANDES DE MODÉRATION
# =========================

@bot.tree.command(name="ban")
@app_commands.describe(member="Le membre à bannir", reason="La raison du ban",
                       delete_days="Jours de messages à supprimer (0-7)")
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "Aucune raison fournie",
              delete_days: int = 7):
    """Bannir un membre du serveur"""

    # Vérifier les permissions
    if not interaction.user.guild_permissions.ban_members:
        embed = discord.Embed(
            title="❌ **PERMISSION REFUSÉE**",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     Tu n'as pas la permission `Bannir des membres`.\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Vérifier que le bot peut ban
    if not interaction.guild.me.guild_permissions.ban_members:
        embed = discord.Embed(
            title="❌ **ERREUR BOT**",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     Je n'ai pas la permission `Bannir des membres`.\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Empêcher de ban un admin
    if member.guild_permissions.administrator:
        embed = discord.Embed(
            title="❌ **ACTION IMPOSSIBLE**",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     Tu ne peux pas bannir un administrateur.\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Empêcher de ban le bot
    if member == interaction.guild.me:
        embed = discord.Embed(
            title="❌ **ACTION IMPOSSIBLE**",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     Tu ne peux pas me bannir moi-même !\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Limiter delete_days entre 0 et 7
    delete_days = max(0, min(7, delete_days))

    try:
        await member.ban(reason=f"{reason} (par {interaction.user})", delete_message_days=delete_days)

        # Confirmation simple (éphémère)
        await interaction.response.send_message(
            f"✅ {member.mention} a été banni.",
            ephemeral=True
        )

        # Log détaillé dans le salon de modération
        log_embed = discord.Embed(
            title="🔨 BAN",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     **Membre :** {member.mention}\n"
                        f"     **Modérateur :** {interaction.user.mention}\n"
                        f"     **Raison :** {reason}\n"
                        f"     **Messages supprimés :** {delete_days} jours\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.dark_red(),
            timestamp=datetime.utcnow()
        )
        log_embed.set_thumbnail(url=member.display_avatar.url)
        await send_log(interaction.guild, "moderation", log_embed)

    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur : {e}", ephemeral=True)


@bot.tree.command(name="kick")
@app_commands.describe(member="Le membre à exclure", reason="La raison du kick")
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "Aucune raison fournie"):
    """Exclure un membre du serveur"""

    # Vérifier les permissions
    if not interaction.user.guild_permissions.kick_members:
        embed = discord.Embed(
            title="❌ **PERMISSION REFUSÉE**",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     Tu n'as pas la permission `Exclure des membres`.\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Vérifier que le bot peut kick
    if not interaction.guild.me.guild_permissions.kick_members:
        embed = discord.Embed(
            title="❌ **ERREUR BOT**",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     Je n'ai pas la permission `Exclure des membres`.\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Empêcher de kick un admin
    if member.guild_permissions.administrator:
        embed = discord.Embed(
            title="❌ **ACTION IMPOSSIBLE**",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     Tu ne peux pas exclure un administrateur.\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Empêcher de kick le bot
    if member == interaction.guild.me:
        embed = discord.Embed(
            title="❌ **ACTION IMPOSSIBLE**",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     Tu ne peux pas m'exclure moi-même !\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    try:
        await member.kick(reason=f"{reason} (par {interaction.user})")

        # Confirmation simple (éphémère)
        await interaction.response.send_message(
            f"✅ {member.mention} a été exclu.",
            ephemeral=True
        )

        # Log détaillé dans le salon de modération
        log_embed = discord.Embed(
            title="👢 KICK",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     **Membre :** {member.mention}\n"
                        f"     **Modérateur :** {interaction.user.mention}\n"
                        f"     **Raison :** {reason}\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        log_embed.set_thumbnail(url=member.display_avatar.url)
        await send_log(interaction.guild, "moderation", log_embed)

    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur : {e}", ephemeral=True)


@bot.tree.command(name="timeout")
@app_commands.describe(member="Le membre à restreindre", duration="Durée (ex: 1h, 30m, 1d)",
                       reason="La raison du timeout")
async def timeout_cmd(interaction: discord.Interaction, member: discord.Member, duration: str,
                      reason: str = "Aucune raison fournie"):
    """Restreindre un membre (timeout) avec durée personnalisée"""

    # Vérifier les permissions
    if not interaction.user.guild_permissions.moderate_members:
        embed = discord.Embed(
            title="❌ **PERMISSION REFUSÉE**",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     Tu n'as pas la permission `Gérer les membres`.\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Vérifier que le bot peut timeout
    if not interaction.guild.me.guild_permissions.moderate_members:
        embed = discord.Embed(
            title="❌ **ERREUR BOT**",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     Je n'ai pas la permission `Gérer les membres`.\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Empêcher de timeout un admin
    if member.guild_permissions.administrator:
        embed = discord.Embed(
            title="❌ **ACTION IMPOSSIBLE**",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     Tu ne peux pas restreindre un administrateur.\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Convertir la durée en timedelta
    try:
        duration_seconds = parse_duration(duration)
        if duration_seconds <= 0:
            raise ValueError("Durée invalide")
        if duration_seconds > 2419200:  # 28 jours max
            embed = discord.Embed(
                title="❌ **DURÉE TROP LONGUE**",
                description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"     La durée maximale est de 28 jours.\n"
                            f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
    except ValueError:
        embed = discord.Embed(
            title="❌ **FORMAT INVALIDE**",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     Formats acceptés : `30s`, `5m`, `2h`, `1d`\n"
                        f"     Exemple : `/timeout @user 1h Spam`\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    try:
        # CORRECTION ICI : utiliser discord.utils.utcnow() au lieu de datetime.utcnow()
        until = discord.utils.utcnow() + timedelta(seconds=duration_seconds)
        await member.timeout(until, reason=f"{reason} (par {interaction.user})")

        # Formater la durée pour l'affichage
        duration_text = format_duration(duration_seconds)

        # Embed de confirmation
        embed = discord.Embed(
            title="⏰ **TIMEOUT EXÉCUTÉ**",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     **Membre :** {member.mention}\n"
                        f"     **Modérateur :** {interaction.user.mention}\n"
                        f"     **Durée :** {duration_text}\n"
                        f"     **Raison :** {reason}\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.yellow(),
            timestamp=datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed)

        # Log dans le salon de modération
        log_embed = discord.Embed(
            title="⏰ TIMEOUT",
            description=f"**Membre :** {member.mention}\n"
                        f"**Modérateur :** {interaction.user.mention}\n"
                        f"**Durée :** {duration_text}\n"
                        f"**Raison :** {reason}",
            color=discord.Color.yellow(),
            timestamp=datetime.utcnow()
        )
        log_embed.set_thumbnail(url=member.display_avatar.url)
        await send_log(interaction.guild, "moderation", log_embed)

    except Exception as e:
        embed = discord.Embed(
            title="❌ **ERREUR**",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     {e}\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.red()
        )


        @bot.tree.command(name="timeout")
        @app_commands.describe(member="Le membre à restreindre", duration="Durée (ex: 1h, 30m, 1d)",
                               reason="La raison du timeout")
        async def timeout_cmd(interaction: discord.Interaction, member: discord.Member, duration: str,
                              reason: str = "Aucune raison fournie"):
            """Restreindre un membre (timeout) avec durée personnalisée"""

            # Vérifier les permissions
            if not interaction.user.guild_permissions.moderate_members:
                embed = discord.Embed(
                    title="❌ **PERMISSION REFUSÉE**",
                    description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"     Tu n'as pas la permission `Gérer les membres`.\n"
                                f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Vérifier que le bot peut timeout
            if not interaction.guild.me.guild_permissions.moderate_members:
                embed = discord.Embed(
                    title="❌ **ERREUR BOT**",
                    description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"     Je n'ai pas la permission `Gérer les membres`.\n"
                                f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Empêcher de timeout un admin
            if member.guild_permissions.administrator:
                embed = discord.Embed(
                    title="❌ **ACTION IMPOSSIBLE**",
                    description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"     Tu ne peux pas restreindre un administrateur.\n"
                                f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Convertir la durée en timedelta
            try:
                duration_seconds = parse_duration(duration)
                if duration_seconds <= 0:
                    raise ValueError("Durée invalide")
                if duration_seconds > 2419200:  # 28 jours max
                    embed = discord.Embed(
                        title="❌ **DURÉE TROP LONGUE**",
                        description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                    f"     La durée maximale est de 28 jours.\n"
                                    f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                        color=discord.Color.red()
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
            except ValueError:
                embed = discord.Embed(
                    title="❌ **FORMAT INVALIDE**",
                    description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"     Formats acceptés : `30s`, `5m`, `2h`, `1d`\n"
                                f"     Exemple : `/timeout @user 1h Spam`\n"
                                f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            try:
                until = discord.utils.utcnow() + timedelta(seconds=duration_seconds)
                await member.timeout(until, reason=f"{reason} (par {interaction.user})")

                duration_text = format_duration(duration_seconds)

                # ===== CONFIRMATION SIMPLE DANS LE SALON (EPHEMERE) =====
                await interaction.response.send_message(
                    f"✅ {member.mention} a été timeout pour {duration_text}.",
                    ephemeral=True  # ← Seule la personne qui a tapé la commande la voit
                )

                # ===== LOG DÉTAILLÉ DANS LE SALON DE MODÉRATION =====
                log_embed = discord.Embed(
                    title="⏰ TIMEOUT",
                    description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"     **Membre :** {member.mention}\n"
                                f"     **Modérateur :** {interaction.user.mention}\n"
                                f"     **Durée :** {duration_text}\n"
                                f"     **Raison :** {reason}\n"
                                f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                    color=discord.Color.yellow(),
                    timestamp=datetime.utcnow()
                )
                log_embed.set_thumbnail(url=member.display_avatar.url)
                await send_log(interaction.guild, "moderation", log_embed)

            except Exception as e:
                await interaction.response.send_message(f"❌ Erreur : {e}", ephemeral=True)


# =========================
# FONCTIONS UTILITAIRES POUR TIMEOUT
# =========================

def parse_duration(duration: str) -> int:
    """Convertit une chaîne comme '1h', '30m', '1d' en secondes"""
    duration = duration.lower().strip()

    if duration.endswith('s'):
        return int(duration[:-1])
    elif duration.endswith('m'):
        return int(duration[:-1]) * 60
    elif duration.endswith('h'):
        return int(duration[:-1]) * 3600
    elif duration.endswith('d'):
        return int(duration[:-1]) * 86400
    else:
        raise ValueError(f"Format invalide: {duration}")


def format_duration(seconds: int) -> str:
    """Convertit les secondes en texte lisible"""
    if seconds < 60:
        return f"{seconds} secondes"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} minutes"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours} heures"
    else:
        days = seconds // 86400
        return f"{days} jours"


# =========================
# COMMANDE POUR LEVER LE TIMEOUT
# =========================

@bot.tree.command(name="untimeout")
@app_commands.describe(member="Le membre à libérer")
async def untimeout(interaction: discord.Interaction, member: discord.Member):
    """Lever le timeout d'un membre"""

    if not interaction.user.guild_permissions.moderate_members:
        embed = discord.Embed(
            title="❌ **PERMISSION REFUSÉE**",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     Tu n'as pas la permission `Gérer les membres`.\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    if not member.timed_out_until:
        embed = discord.Embed(
            title="❌ **PAS DE TIMEOUT**",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     {member.mention} n'est pas en timeout.\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    try:
        await member.timeout(None, reason=f"Timeout levé par {interaction.user}")

        # Confirmation simple
        await interaction.response.send_message(
            f"✅ Timeout levé pour {member.mention}.",
            ephemeral=True
        )

        # Log détaillé
        log_embed = discord.Embed(
            title="✅ TIMEOUT LEVÉ",
            description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"     **Membre :** {member.mention}\n"
                        f"     **Modérateur :** {interaction.user.mention}\n"
                        f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        log_embed.set_thumbnail(url=member.display_avatar.url)
        await send_log(interaction.guild, "moderation", log_embed)

    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur : {e}", ephemeral=True)


# =========================
# COMMANDES DE NIVEAUX VOCAUX
# =========================

@bot.tree.command(name="setvocallevel")
async def setvocallevel(interaction: discord.Interaction, channel: discord.TextChannel):
    """Définit le salon où seront envoyés les messages de niveau supérieur"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Permission administrateur requise.", ephemeral=True)
        return

    vocal_level_channel[interaction.guild.id] = channel.id
    await interaction.response.send_message(f"✅ Les annonces de niveau seront envoyées dans {channel.mention}")


@bot.tree.command(name="setvocalimage")
async def setvocalimage(interaction: discord.Interaction, url: str):
    """Définit une image d'arrière-plan pour les messages de niveau"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Permission administrateur requise.", ephemeral=True)
        return

    vocal_level_image[interaction.guild.id] = url
    await interaction.response.send_message(f"✅ Image de niveau définie !")


@bot.tree.command(name="level")
async def level(interaction: discord.Interaction, member: discord.Member = None):
    """Affiche le niveau vocal d'un membre"""
    target = member or interaction.user
    user_id = target.id

    xp = vocal_xp.get(user_id, 0)
    level = get_level_from_xp(xp)
    xp_current, xp_needed, progress = get_xp_progress(xp, level)

    # Créer une barre de progression esthétique
    bar_length = 20
    filled = int(progress / 100 * bar_length)
    bar = "🟩" * filled + "⬜" * (bar_length - filled)

    # Récupérer l'image personnalisée
    image_url = vocal_level_image.get(interaction.guild.id)

    embed = discord.Embed(
        title="🎙️ **CLASSEMENT VOCAL** 🎙️",
        description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"     👤 **Membre :** {target.mention}\n"
                    f"     🏆 **Niveau :** `{level}`\n"
                    f"     ⭐ **XP total :** `{xp}`\n\n"
                    f"     **Progression vers niveau {level + 1} :**\n"
                    f"     `{xp_current}/{xp_needed} XP`\n"
                    f"     {bar} `{progress}%`\n"
                    f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        color=discord.Color.green()
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    if image_url:
        embed.set_image(url=image_url)
    embed.set_footer(text="🎤 Plus tu parles en vocal, plus tu montes de niveau !")

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="leaderboard_vocal")
async def leaderboard_vocal(interaction: discord.Interaction):
    """Affiche le classement des meilleurs niveaux vocaux"""

    if not vocal_xp:
        await interaction.response.send_message("📊 Pas encore de données vocales sur ce serveur.")
        return

    # Trier par XP décroissant
    sorted_users = sorted(vocal_xp.items(), key=lambda x: x[1], reverse=True)[:10]

    embed = discord.Embed(
        title="🏆 **CLASSEMENT VOCAL** 🏆",
        description="┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        color=discord.Color.gold()
    )

    medals = ["🥇", "🥈", "🥉"]
    for i, (user_id, xp) in enumerate(sorted_users, 1):
        member = interaction.guild.get_member(user_id)
        if member:
            name = member.display_name
        else:
            name = f"Utilisateur {user_id}"

        level = get_level_from_xp(xp)
        medal = medals[i - 1] if i <= 3 else f"{i}."

        embed.add_field(
            name=f"{medal} {name}",
            value=f"┣ Niveau : `{level}`\n┗ XP : `{xp}`",
            inline=False
        )

    embed.set_footer(text="🎙️ Continue de parler en vocal pour monter de niveau !")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="set_vocal_xp")
async def set_vocal_xp(interaction: discord.Interaction, member: discord.Member, amount: int):
    """Ajoute de l'XP à un membre (admin seulement - pour tester)"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Permission administrateur requise.", ephemeral=True)
        return

    if amount < 0:
        await interaction.response.send_message("❌ Le montant doit être positif.", ephemeral=True)
        return

    old_xp = vocal_xp.get(member.id, 0)
    old_level = get_level_from_xp(old_xp)

    vocal_xp[member.id] = old_xp + amount

    new_level = get_level_from_xp(vocal_xp[member.id])

    embed = discord.Embed(
        title="✨ **XP AJOUTÉE** ✨",
        description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"     👤 **Membre :** {member.mention}\n"
                    f"     ➕ **XP ajoutée :** `+{amount}`\n"
                    f"     📊 **Nouveau total :** `{vocal_xp[member.id]}`\n"
                    f"     🏆 **Niveau :** `{old_level}` → `{new_level}`\n"
                    f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="reset_vocal_xp")
async def reset_vocal_xp(interaction: discord.Interaction, member: discord.Member):
    """Réinitialise l'XP vocale d'un membre (admin seulement)"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Permission administrateur requise.", ephemeral=True)
        return

    vocal_xp[member.id] = 0

    embed = discord.Embed(
        title="🔄 **XP RÉINITIALISÉE**",
        description=f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"     👤 **Membre :** {member.mention}\n"
                    f"     📊 **XP :** `0`\n"
                    f"     🏆 **Niveau :** `1`\n"
                    f"     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        color=discord.Color.orange(),
        timestamp=datetime.utcnow()
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    await interaction.response.send_message(embed=embed)


# =========================
# RUN
# =========================
if __name__ == "__main__":
    TOKEN = "TON_NOUVEAU_TOKEN"
    bot.run(TOKEN)