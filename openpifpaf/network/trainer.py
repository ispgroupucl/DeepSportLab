"""Train a pifpaf net."""
import argparse
import os
import copy
import hashlib
import logging
import shutil
import time
import torch
import datetime
from torch.utils.tensorboard import SummaryWriter
import socket

LOG = logging.getLogger(__name__)

import wandb
import numpy as np
import math

# import torch.autograd.profiler as profiler
# wandb.login()

def log_wandb(in_dict):
    wandb.log(in_dict)


def apply(f, items):
    """Apply f in a nested fashion to all items that are not list or tuple."""
    if items is None:
        return None
    if isinstance(items, (list, tuple)):
        return [apply(f, i) for i in items]
    if isinstance(items, dict):
        return {k: apply(f, v) for k, v in items.items()}
    return f(items)


class Trainer(object):
    def __init__(self, model, loss, optimizer, out, *,
                 lr_scheduler=None,
                 log_interval=10,
                 device=None,
                 fix_batch_norm=False,
                 stride_apply=1,
                 ema_decay=None,
                 train_profile=None,
                 model_meta_data=None,
                 train_args=None,):
        self.model = model
        self.loss = loss
        self.optimizer = optimizer
        self.out = out
        self.lr_scheduler = lr_scheduler

        self.log_interval = log_interval
        self.device = device
        self.fix_batch_norm = fix_batch_norm
        self.stride_apply = stride_apply

        self.ema_decay = ema_decay
        self.ema = None
        self.ema_restore_params = None

        self.model_meta_data = model_meta_data
        self.train_args = train_args

        if not self.train_args.disable_wandb:
            wandb.login()

        
        ### tb stuff
        tb_datetime = datetime.datetime.now()
        tb_hostname = socket.gethostname()
        checkpoint = torch.load(self.train_args.checkpoint) if self.train_args.checkpoint else None
        filename = os.path.basename(self.train_args.output)
        self.tb_filename = os.path.join('runs', filename)
        self.writer = SummaryWriter(self.tb_filename)
        self.LOSS_NAMES = ['PIF Confidence', 'PIF Localization', 'PIF Scale', 'PAN Semantic', 'PAN Offset', 'PIF Ball Confidence', 'PIF Ball Localization', 'PIF Ball Scale', 'PIF CENT Confidence', 'PIF CENT Localization', 'PIF CENT Scale']

        
        if not self.train_args.disable_wandb:
            if checkpoint is not None:
                if 'wandb_id' in checkpoint:
                    self.wandb_id = checkpoint['wandb_id']
                    print('wandb_id from checkpoint', self.wandb_id)
            else:
                self.wandb_id = wandb.util.generate_id()
                print('new wandb_id', self.wandb_id)

            self.wandb_dir = train_args.wandb_dir
    
            wandb.init(project='DeepSportLab', entity='deepsport', id=self.wandb_id, config=train_args, resume='allow', dir=self.wandb_dir)

            wandb.watch(self.model, log="all", log_freq=5000)

        if train_profile:
            # monkey patch to profile self.train_batch()
            self.trace_counter = 0
            self.train_batch_without_profile = self.train_batch
            def train_batch_with_profile(*args, **kwargs):
                with torch.autograd.profiler.profile(use_cuda=True) as prof:
                    result = self.train_batch_without_profile(*args, **kwargs)
                print(prof.key_averages())
                self.trace_counter += 1
                tracefilename = train_profile.replace(
                    '.json', '.{}.json'.format(self.trace_counter))
                LOG.info('writing trace file %s', tracefilename)
                prof.export_chrome_trace(tracefilename)
                return result
            self.train_batch = train_batch_with_profile
        LOG.info({
            'type': 'config',
            # 'field_names': self.loss.field_names,
        })

    def lr(self):
        for param_group in self.optimizer.param_groups:
            return param_group['lr']

    def step_ema(self):
        if self.ema is None:
            return

        for p, ema_p in zip(self.model.parameters(), self.ema):
            ema_p.mul_(1.0 - self.ema_decay).add_(self.ema_decay, p.data)

    def apply_ema(self):
        if self.ema is None:
            return

        LOG.info('applying ema')
        self.ema_restore_params = copy.deepcopy(
            [p.data for p in self.model.parameters()])
        for p, ema_p in zip(self.model.parameters(), self.ema):
            p.data.copy_(ema_p)

    def ema_restore(self):
        if self.ema_restore_params is None:
            return

        LOG.info('restoring params from before ema')
        for p, ema_p in zip(self.model.parameters(), self.ema_restore_params):
            p.data.copy_(ema_p)
        self.ema_restore_params = None

    def loop(self, train_scenes, val_scenes, epochs, start_epoch=0):
        if self.lr_scheduler is not None:
            for _ in range(start_epoch * len(train_scenes)):
                self.lr_scheduler.step()
        

        for epoch in range(start_epoch, epochs):

            if epoch==0:
                self.write_state_dict(epoch, epoch == epochs - 1)    

            # freeze encoder
            if epoch < self.train_args.lr_warm_up_epochs and self.train_args.enable_freeze_encoder:
                self.freeze_backbone()
                print('backbone freezed')
            # unfreeze encoder
            elif epoch == self.train_args.lr_warm_up_epochs and self.train_args.enable_freeze_encoder:
                self.unfreeze_backbone()
                print('backbone unfreezed')

            self.train(train_scenes, epoch)


            self.write_state_dict(epoch+1, epoch == epochs - 1)
            self.val(val_scenes, epoch + 1)
            
            self.writer.flush()






    def train_batch(self, data, targets, apply_gradients=True, batch_idx=None, epoch=None, meta=None):  # pylint: disable=method-hidden

        if self.device:
            data = data.to(self.device, non_blocking=True)
                           
            targets = apply(lambda x: x.to(self.device), targets)

        # train encoder
        with torch.autograd.profiler.record_function('model'):
            outputs = self.model(data)
            
            

        with torch.autograd.profiler.record_function('loss'):
            loss, head_losses = self.loss(outputs, targets)
        if loss is not None:
            with torch.autograd.profiler.record_function('backward'):
                loss.backward()

        if apply_gradients:
            with torch.autograd.profiler.record_function('step'):
                self.optimizer.step()
                self.optimizer.zero_grad()
            with torch.autograd.profiler.record_function('ema'):
                self.step_ema()



        return (
            float(loss.detach().item()) if loss is not None else None,
            [float(l.detach().item()) if l is not None else None
             for l in head_losses],
        )

    def val_batch(self, data, targets, batch_idx=None, epoch=None):

        if self.device:
            data = data.to(self.device, non_blocking=True)


            targets = apply(lambda x: x.to(self.device), targets)
                

        with torch.no_grad():
            outputs = self.model(data)
            
            loss, head_losses = self.loss(outputs, targets)



        return (
            float(loss.detach().item()) if loss is not None else None,
            [float(l.detach().item()) if l is not None else None
             for l in head_losses],
        )

    def train(self, scenes, epoch):
        start_time = time.time()
        self.model.train()
        if self.fix_batch_norm:
            for m in self.model.modules():
                if isinstance(m, (torch.nn.BatchNorm1d, torch.nn.BatchNorm2d)):

                    m.eval()


        self.ema_restore()
        self.ema = None

        epoch_loss = 0.0
        head_epoch_losses = None
        head_epoch_counts = None
        last_batch_end = time.time()
        self.optimizer.zero_grad()
        
        
        for batch_idx, (data, target, meta) in enumerate(scenes):

            preprocess_time = time.time() - last_batch_end
            

            batch_start = time.time()
            apply_gradients = batch_idx % self.stride_apply == 0

            
            loss, head_losses = self.train_batch(data, target, apply_gradients, batch_idx=batch_idx, epoch=epoch, meta=meta)

            for ix, hl in enumerate(head_losses):
                if hl is not None:
                    if math.isnan(hl) or math.isinf(hl):
                        print('Head_loss: ' + str(ix) + str(hl))
                        print('All head losses:', head_losses)
                        print('loss:', loss)
                        


            # update epoch accumulates
            if loss is not None:
                epoch_loss += loss
            if head_epoch_losses is None:
                head_epoch_losses = [0.0 for _ in head_losses]
                head_epoch_counts = [0 for _ in head_losses]
            for i, head_loss in enumerate(head_losses):
                if head_loss is None:
                    continue
                head_epoch_losses[i] += head_loss
                head_epoch_counts[i] += 1

            batch_time = time.time() - batch_start

            
            if not self.train_args.disable_wandb:
                in_dict = {
                    "train loss": loss,
                    'lr': self.lr(),
                    'batch_idx': epoch * len(scenes) + batch_idx,
                    'epoch': epoch+1,
                    }
                
                for hd_idx, head_ls in enumerate(head_losses):
                    in_dict["train loss/ head"+self.LOSS_NAMES[hd_idx]] = head_ls
                    if hasattr(self.loss, 'batch_meta'):
                        sigmas = self.loss.batch_meta()
                        in_dict["Sigma/ head"+ self.LOSS_NAMES[hd_idx]] = .5/sigmas['mtl_sigmas'][hd_idx]**2

                log_wandb(in_dict)

            # write training loss
            if batch_idx % self.log_interval == 0:
                batch_info = {
                    'type': 'train',
                    'epoch': epoch, 'batch_progress': str(round((batch_idx/len(scenes))*100, 2))+'%', 'batch': batch_idx, 'n_batches': len(scenes),
                    'time': round(batch_time, 3),
                    'data_time': round(preprocess_time, 3),
                    'lr': round(self.lr(), 8),
                    'loss': round(loss, 3) if loss is not None else None,
                    'head_losses': [round(l, 3) if l is not None else None
                                    for l in head_losses],
                }
                if hasattr(self.loss, 'batch_meta'):
                    batch_info.update(self.loss.batch_meta())
                LOG.info(batch_info)

            # initialize ema
            if self.ema is None and self.ema_decay:
                self.ema = copy.deepcopy([p.data for p in self.model.parameters()])

            # update learning rate
            if self.lr_scheduler is not None:
                self.lr_scheduler.step()

            last_batch_end = time.time()

        self.apply_ema()
        LOG.info({
            'type': 'train-epoch',
            'epoch': epoch + 1,
            'loss': round(epoch_loss / len(scenes), 5),
            'head_losses': [round(l / max(1, c), 5)
                            for l, c in zip(head_epoch_losses, head_epoch_counts)],
            'time': round(time.time() - start_time, 1),
        })

        if not self.train_args.disable_wandb:
            in_dict = {
                "Epoch/train loss":  epoch_loss / len(scenes),
                "Epoch/epoch": epoch+1,
                "Epoch/train_epoch": epoch+1,
                }

            for hd_idx, head_ls in enumerate(head_epoch_losses):
                in_dict["Epoch/train loss head "+self.LOSS_NAMES[hd_idx]] = head_ls / max(1, head_epoch_counts[hd_idx])
            
            log_wandb(in_dict)


        ########### tensorboard stuff 
        self.writer.add_scalar('Learning Rate/lr ', self.lr(), epoch + 1)
        if hasattr(self.loss, 'batch_meta'):
            for lambda_index, lambda_value in enumerate(self.loss.batch_meta()["lambdas"]):
                self.writer.add_scalar(f'Lambdas/{self.LOSS_NAMES[lambda_index]} ', lambda_value, epoch + 1)
        try:
            self.writer.add_scalar('Train Loss/Total loss', epoch_loss / len(scenes), epoch + 1)
            if hasattr(self.loss, 'batch_meta'):
                sigmas = self.loss.batch_meta()
            for hd_idx, head_ls in enumerate(head_epoch_losses):
                self.writer.add_scalar('Train Loss/head '+ self.LOSS_NAMES[hd_idx], head_ls / max(1, head_epoch_counts[hd_idx]), epoch + 1)
                if hasattr(self.loss, 'batch_meta'):
                    self.writer.add_scalar('Sigmas/head '+ self.LOSS_NAMES[hd_idx], .5/sigmas['mtl_sigmas'][hd_idx]**2, epoch + 1)
                              
        except:
            print('error')

    def val(self, scenes, epoch):
        start_time = time.time()

        # Train mode implies outputs are for losses, so have to use it here.
        self.model.train()
        if self.fix_batch_norm:
            for m in self.model.modules():
                if isinstance(m, (torch.nn.BatchNorm1d, torch.nn.BatchNorm2d)):
                    m.eval()

        epoch_loss = 0.0
        head_epoch_losses = None
        head_epoch_counts = None
        

        for batch_idx, (data, target, meta) in enumerate(scenes):
            self.data_end = copy.deepcopy(data)
            loss, head_losses = self.val_batch(data, target,batch_idx=batch_idx, epoch=epoch)

            for ix, hl in enumerate(head_losses):
                if hl is not None:
                    if math.isnan(hl) or math.isinf(hl):
                        print('Head_loss: ' + str(ix) + str(hl))
                        print('All head losses:', head_losses)
                        print('loss:', loss)
                        
            # update epoch accumulates
            if loss is not None:
                epoch_loss += loss
            if head_epoch_losses is None:
                head_epoch_losses = [0.0 for _ in head_losses]
                head_epoch_counts = [0 for _ in head_losses]
            for i, head_loss in enumerate(head_losses):
                if head_loss is None:
                    continue
                head_epoch_losses[i] += head_loss
                head_epoch_counts[i] += 1
                
            

            eval_time = time.time() - start_time

            if not self.train_args.disable_wandb:
                in_dict = {
                    "val loss": loss,
                    'lr': self.lr(),
                    'batch_idx_val': epoch * len(scenes) + batch_idx,
                    }
                for hd_idx, head_ls in enumerate(head_losses):
                    in_dict["val loss/ head"+self.LOSS_NAMES[hd_idx]] = head_ls
                log_wandb(in_dict)

        LOG.info({
            'type': 'val-epoch',
            'epoch': epoch,
            'loss': round(epoch_loss / len(scenes), 5),
            'head_losses': [round(l / max(1, c), 5)
                            for l, c in zip(head_epoch_losses, head_epoch_counts)],
            'time': round(eval_time, 1),
        })

        if not self.train_args.disable_wandb:
            in_dict = {
                "Epoch/val loss":  epoch_loss / len(scenes),
                "Epoch/epoch": epoch,
                "Epoch/val_epoch": epoch,
                }

            for hd_idx, head_ls in enumerate(head_epoch_losses):
                in_dict["Epoch/val loss head "+self.LOSS_NAMES[hd_idx]] = head_ls / max(1, head_epoch_counts[hd_idx])
            
            log_wandb(in_dict)

       
        ########### tensorboard stuff 
        try:
            self.writer.add_scalar('Val Loss/Total loss', epoch_loss / len(scenes), epoch)
            for hd_idx, head_ls in enumerate(head_epoch_losses):
                self.writer.add_scalar('Val Loss/head '+ self.LOSS_NAMES[hd_idx], head_ls / max(1, head_epoch_counts[hd_idx]), epoch)
        except:
            print('error')

    def write_model(self, epoch, final=True):
        self.model.cpu()

        if isinstance(self.model, torch.nn.DataParallel):
            LOG.debug('Writing a dataparallel model.')
            model = self.model.module
        else:
            LOG.debug('Writing a single-thread model.')
            model = self.model

        filename = '{}.epoch{:03d}'.format(self.out, epoch)
        LOG.debug('about to write model')
        torch.save({
            'model': model,
            'epoch': epoch,
            'meta': self.model_meta_data,
            'tb_filename': os.path.basename(self.tb_filename),
        }, filename)
        LOG.debug('model written')

        if final:
            sha256_hash = hashlib.sha256()
            with open(filename, 'rb') as f:
                for byte_block in iter(lambda: f.read(8192), b''):
                    sha256_hash.update(byte_block)
            file_hash = sha256_hash.hexdigest()
            outname, _, outext = self.out.rpartition('.')
            final_filename = '{}-{}.{}'.format(outname, file_hash[:8], outext)
            shutil.copyfile(filename, final_filename)

        self.model.to(self.device)

    def write_state_dict(self, epoch, final=True):
        self.model.cpu()

        if isinstance(self.model, torch.nn.DataParallel):
            LOG.debug('Writing a dataparallel model.')
            model = self.model.module
        else:
            LOG.debug('Writing a single-thread model.')
            model = self.model

        filename = '{}.epoch{:03d}'.format(self.out, epoch)
        LOG.debug('about to write model')
        # self.model_meta_data['basenet'] = model.base_net

        if not self.train_args.disable_wandb:
            torch.save({
                'model_state_dict': model.state_dict(),
                'optimizer_state_dict': self.optimizer.state_dict(),
                'epoch': epoch,
                'meta': self.model_meta_data,
                'tb_filename': os.path.basename(self.tb_filename),
                'wandb_id': self.wandb_id
            }, filename)
        else:
            torch.save({
                'model_state_dict': model.state_dict(),
                'optimizer_state_dict': self.optimizer.state_dict(),
                'epoch': epoch,
                'meta': self.model_meta_data,
                'tb_filename': os.path.basename(self.tb_filename),
            }, filename)

        LOG.debug('model written')

        if final:
            sha256_hash = hashlib.sha256()
            with open(filename, 'rb') as f:
                for byte_block in iter(lambda: f.read(8192), b''):
                    sha256_hash.update(byte_block)
            file_hash = sha256_hash.hexdigest()
            outname, _, outext = self.out.rpartition('.')
            final_filename = '{}-{}.{}'.format(outname, file_hash[:8], outext)
            shutil.copyfile(filename, final_filename)

        self.model.to(self.device)

    def close_tb(self):
        self.writer.close()


    def freeze_backbone(self):
        for param in self.model.base_net.parameters():
            param.requires_grad = False

        for param in self.model.head_nets.parameters():
            assert param.requires_grad == True

    def unfreeze_backbone(self):
        for param in self.model.base_net.parameters():
            param.requires_grad = True

        for param in self.model.head_nets.parameters():
            assert param.requires_grad == True


