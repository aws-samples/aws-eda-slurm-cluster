
from aws_cdk import (
    Duration,
    Stack,
    aws_ec2 as ec2,
    CfnOutput,
    Tags,
)
from constructs import Construct
import logging

logger = logging.getLogger(__file__)
logger_formatter = logging.Formatter('%(levelname)s: %(message)s')
logger_streamHandler = logging.StreamHandler()
logger_streamHandler.setFormatter(logger_formatter)
logger.addHandler(logger_streamHandler)
logger.propagate = False
logger.setLevel(logging.INFO)

class CreateSlurmSecurityGroupsStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.config = {
            'VpcId': self.node.try_get_context('vpc_id')
        }
        logger.info(f"VpcId: {self.config['VpcId']}")
        self.vpc = ec2.Vpc.from_lookup(self, "Vpc", vpc_id = self.config['VpcId'])

        security_groups = {}
        fsx_client_security_groups = {}
        lustre_security_groups = {}
        ontap_security_groups = {}
        zfs_security_groups = {}

        # Create New security groups

        slurm_login_node_sg = ec2.SecurityGroup(self, "SlurmLoginNodeSG", vpc=self.vpc, allow_all_outbound=False, description="SlurmLoginNode Security Group")
        Tags.of(slurm_login_node_sg).add("res:Resource", "vdi-security-group")
        security_groups['SlurmLoginNodeSG'] = slurm_login_node_sg
        fsx_client_security_groups['SlurmLoginNodeSG'] = slurm_login_node_sg
        lustre_security_groups['SlurmLoginNodeSG'] = slurm_login_node_sg

        slurm_head_node_sg = ec2.SecurityGroup(self, "SlurmHeadNodeSG", vpc=self.vpc, allow_all_outbound=False, description="SlurmHeadNode Security Group")
        security_groups['SlurmHeadNodeSG'] = slurm_head_node_sg
        fsx_client_security_groups['SlurmHeadNodeSG'] = slurm_head_node_sg
        lustre_security_groups['SlurmHeadNodeSG'] = slurm_head_node_sg

        slurm_compute_node_sg = ec2.SecurityGroup(self, "SlurmComputeNodeSG", vpc=self.vpc, allow_all_outbound=False, description="SlurmComputeNode Security Group")
        security_groups['SlurmComputeNodeSG'] = slurm_compute_node_sg
        fsx_client_security_groups['SlurmComputeNodeSG'] = slurm_compute_node_sg
        lustre_security_groups['SlurmComputeNodeSG'] = slurm_compute_node_sg

        slurm_fsx_lustre_sg = ec2.SecurityGroup(self, "SlurmFsxLustreSG", vpc=self.vpc, allow_all_outbound=False, description="SlurmFsxLustre Security Group")
        security_groups['SlurmFsxLustreSG'] = slurm_fsx_lustre_sg
        lustre_security_groups['SlurmFsxLustreSG'] = slurm_fsx_lustre_sg

        slurm_fsx_ontap_sg = ec2.SecurityGroup(self, "SlurmFsxOntapSG", vpc=self.vpc, allow_all_outbound=True, description="SlurmFsxOntap Security Group")
        security_groups['SlurmFsxOntapSG'] = slurm_fsx_ontap_sg
        ontap_security_groups['SlurmFsxOntapSG'] = slurm_fsx_ontap_sg

        slurm_fsx_zfs_sg = ec2.SecurityGroup(self, "SlurmFsxZfsSG", vpc=self.vpc, allow_all_outbound=False, description="SlurmFsxZfs Security Group")
        security_groups['SlurmFsxZfsSG'] = slurm_fsx_zfs_sg
        zfs_security_groups['SlurmFsxZfsSG'] = slurm_fsx_zfs_sg

        for sg_name, sg in security_groups.items():
            Tags.of(sg).add("Name", f"{self.stack_name}-{sg_name}")

        # Create objects for existing security groups

        existing_fsxl_security_group_id = self.node.try_get_context('fsxl_security_group_id')
        if existing_fsxl_security_group_id:
            existing_fsx_lustre_sg = ec2.SecurityGroup.from_security_group_id(
                self, 'ExistingFsxLustreSG',
                security_group_id = existing_fsxl_security_group_id
            )
            security_groups['ExistingFsxLustreSG'] = existing_fsx_lustre_sg
            lustre_security_groups['ExistingFsxLustreSG'] = existing_fsx_lustre_sg

        existing_fsxo_security_group_id = self.node.try_get_context('fsxo_security_group_id')
        if existing_fsxo_security_group_id:
            existing_fsx_ontap_sg = ec2.SecurityGroup.from_security_group_id(
                self, 'ExistingFsxOntapSG',
                security_group_id = existing_fsxo_security_group_id
            )
            security_groups['ExistingFsxOntapSG'] = existing_fsx_ontap_sg
            ontap_security_groups['ExistingFsxOntapSG'] = existing_fsx_ontap_sg

        existing_fsxz_security_group_id = self.node.try_get_context('fsxz_security_group_id')
        if existing_fsxz_security_group_id:
            existing_fsx_zfs_sg = ec2.SecurityGroup.from_security_group_id(
                self, 'ExistingFsxZfsSG',
                security_group_id = existing_fsxz_security_group_id
            )
            security_groups['ExistingFsxZfsSG'] = existing_fsx_zfs_sg
            zfs_security_groups['ExistingFsxZfsSG'] = existing_fsx_zfs_sg

        slurmdbd_sg = None
        slurmdbd_security_group_id = self.node.try_get_context('slurmdbd_security_group_id')
        if slurmdbd_security_group_id:
            slurmdbd_sg = ec2.SecurityGroup.from_security_group_id(
                self, 'SlurmdbdSG',
                security_group_id = slurmdbd_security_group_id
            )
            security_groups['SlurmdbdSG'] = slurmdbd_sg

        # Rules for compute nodes
        # Allow mounting of /opt/slurm and from head node
        slurm_compute_node_sg.connections.allow_to(slurm_head_node_sg, ec2.Port.tcp(2049), f"SlurmComputeNodeSG to SlurmHeadNodeSG NFS")

        # Rules for login nodes
        slurm_login_node_sg.connections.allow_from(slurm_head_node_sg, ec2.Port.tcp_range(1024, 65535), f"SlurmHeadNodeSG to SlurmLoginNodeSG ephemeral")
        slurm_login_node_sg.connections.allow_from(slurm_compute_node_sg, ec2.Port.tcp_range(1024, 65535), f"SlurmComputeNodeSG to SlurmLoginNodeSG ephemeral")
        slurm_login_node_sg.connections.allow_from(slurm_compute_node_sg, ec2.Port.tcp_range(1024, 65535), f"SlurmComputeNodeSG to SlurmLoginNodeSG X11")
        slurm_login_node_sg.connections.allow_to(slurm_head_node_sg, ec2.Port.tcp(2049), f"SlurmLoginNodeSG to SlurmHeadNodeSG NFS")
        slurm_login_node_sg.connections.allow_to(slurm_compute_node_sg, ec2.Port.tcp(6818), f"SlurmComputeNodeSG to SlurmHeadNodeSG slurmd")
        slurm_login_node_sg.connections.allow_to(slurm_head_node_sg, ec2.Port.tcp(6819), f"SlurmLoginNodeSG to SlurmHeadNodeSG slurmdbd")
        if slurmdbd_sg:
            slurm_login_node_sg.connections.allow_to(slurmdbd_sg, ec2.Port.tcp(6819), f"SlurmLoginNodeSG to SlurmDbdSG slurmdbd")
        slurm_login_node_sg.connections.allow_to(slurm_head_node_sg, ec2.Port.tcp_range(6820, 6829), f"SlurmLoginNodeSG to SlurmHeadNodeSG slurmctld")
        slurm_login_node_sg.connections.allow_to(slurm_head_node_sg, ec2.Port.tcp(6830), f"SlurmLoginNodeSG to SlurmHeadNodeSG slurmrestd")

        # Rules for FSx Lustre
        for src_sg_name, src_sg in lustre_security_groups.items():
            for dst_sg_name, dst_sg in lustre_security_groups.items():
                src_sg.connections.allow_to(dst_sg, ec2.Port.tcp(988), f"{src_sg_name} to {dst_sg_name} lustre")
                src_sg.connections.allow_to(dst_sg, ec2.Port.tcp_range(1018, 1023), f"{src_sg_name} to {dst_sg_name} lustre")
                # It shouldn't be necessary to do allow_to and allow_from, but CDK left off the ingress rule form lustre to lustre if I didn't add the allow_from.
                dst_sg.connections.allow_from(src_sg, ec2.Port.tcp(988), f"{src_sg_name} to {dst_sg_name} lustre")
                dst_sg.connections.allow_from(src_sg, ec2.Port.tcp_range(1018, 1023), f"{src_sg_name} to {dst_sg_name} lustre")

        # Rules for FSx Ontap
        for fsx_client_sg_name, fsx_client_sg in fsx_client_security_groups.items():
            for fsx_ontap_sg_name, fsx_ontap_sg in ontap_security_groups.items():
                fsx_client_sg.connections.allow_to(fsx_ontap_sg, ec2.Port.tcp(111), f"{fsx_client_sg_name} to {fsx_ontap_sg_name} rpc for NFS")
                fsx_client_sg.connections.allow_to(fsx_ontap_sg, ec2.Port.udp(111), f"{fsx_client_sg_name} to {fsx_ontap_sg_name} rpc for NFS")
                fsx_client_sg.connections.allow_to(fsx_ontap_sg, ec2.Port.tcp(635), f"{fsx_client_sg_name} to {fsx_ontap_sg_name} NFS mount")
                fsx_client_sg.connections.allow_to(fsx_ontap_sg, ec2.Port.udp(635), f"{fsx_client_sg_name} to {fsx_ontap_sg_name} NFS mount")
                fsx_client_sg.connections.allow_to(fsx_ontap_sg, ec2.Port.tcp(2049), f"{fsx_client_sg_name} to {fsx_ontap_sg_name} NFS server daemon")
                fsx_client_sg.connections.allow_to(fsx_ontap_sg, ec2.Port.udp(2049), f"{fsx_client_sg_name} to {fsx_ontap_sg_name} NFS server daemon")
                fsx_client_sg.connections.allow_to(fsx_ontap_sg, ec2.Port.tcp(4045), f"{fsx_client_sg_name} to {fsx_ontap_sg_name} NFS lock daemon")
                fsx_client_sg.connections.allow_to(fsx_ontap_sg, ec2.Port.udp(4045), f"{fsx_client_sg_name} to {fsx_ontap_sg_name} NFS lock daemon")
                fsx_client_sg.connections.allow_to(fsx_ontap_sg, ec2.Port.tcp(4046), f"{fsx_client_sg_name} to {fsx_ontap_sg_name} Network status monitor for NFS")
                fsx_client_sg.connections.allow_to(fsx_ontap_sg, ec2.Port.udp(4046), f"{fsx_client_sg_name} to {fsx_ontap_sg_name} Network status monitor for NFS")

            for fsx_zfs_sg_name, fsx_zfs_sg in zfs_security_groups.items():
                fsx_client_sg.connections.allow_to(fsx_zfs_sg, ec2.Port.tcp(111), f"{fsx_client_sg_name} to {fsx_zfs_sg_name} rpc for NFS")
                fsx_client_sg.connections.allow_to(fsx_zfs_sg, ec2.Port.udp(111), f"{fsx_client_sg_name} to {fsx_zfs_sg_name} rpc for NFS")
                fsx_client_sg.connections.allow_to(fsx_zfs_sg, ec2.Port.tcp(2049), f"{fsx_client_sg_name} to {fsx_zfs_sg_name} NFS server daemon")
                fsx_client_sg.connections.allow_to(fsx_zfs_sg, ec2.Port.udp(2049), f"{fsx_client_sg_name} to {fsx_zfs_sg_name} NFS server daemon")
                fsx_client_sg.connections.allow_to(fsx_zfs_sg, ec2.Port.tcp_range(20001, 20003), f"{fsx_client_sg_name} to {fsx_zfs_sg_name} NFS mount, status monitor, and lock daemon")
                fsx_client_sg.connections.allow_to(fsx_zfs_sg, ec2.Port.udp_range(20001, 20003), f"{fsx_client_sg_name} to {fsx_zfs_sg_name} NFS mount, status monitor, and lock daemon")
                # There is a bug in PC 3.10.1 that requires outbound traffic to be enabled even though ZFS doesn't.
                # Remove when bug in PC is fixed.
                # Tracked by https://github.com/aws-samples/aws-eda-slurm-cluster/issues/253
                fsx_client_sg.connections.allow_from(fsx_zfs_sg, ec2.Port.tcp(111), f"{fsx_zfs_sg_name} to {fsx_client_sg_name} rpc for NFS")
                fsx_client_sg.connections.allow_from(fsx_zfs_sg, ec2.Port.udp(111), f"{fsx_zfs_sg_name} to {fsx_client_sg_name} rpc for NFS")
                fsx_client_sg.connections.allow_from(fsx_zfs_sg, ec2.Port.tcp(2049), f"{fsx_zfs_sg_name} to {fsx_client_sg_name} NFS server daemon")
                fsx_client_sg.connections.allow_from(fsx_zfs_sg, ec2.Port.udp(2049), f"{fsx_zfs_sg_name} to {fsx_client_sg_name} NFS server daemon")
                fsx_client_sg.connections.allow_from(fsx_zfs_sg, ec2.Port.tcp_range(20001, 20003), f"{fsx_zfs_sg_name} to {fsx_client_sg_name} NFS mount, status monitor, and lock daemon")
                fsx_client_sg.connections.allow_from(fsx_zfs_sg, ec2.Port.udp_range(20001, 20003), f"{fsx_zfs_sg_name} to {fsx_client_sg_name} NFS mount, status monitor, and lock daemon")

        for sg_name, sg in security_groups.items():
            CfnOutput(self, f"{sg_name}Id",
                value = sg.security_group_id
            )
