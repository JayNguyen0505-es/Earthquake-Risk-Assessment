package vn.vast.vasteq.user;

import java.time.LocalDateTime;
import java.time.ZoneOffset;
import com.fasterxml.jackson.annotation.JsonIgnore;
import jakarta.persistence.*;

@Entity
@Table(name="users", uniqueConstraints=@UniqueConstraint(name="uq_users_email",columnNames="email"))
public class User {
    public enum Role { admin, user, guest }
    @Id @GeneratedValue(strategy=GenerationType.IDENTITY)
    @Column(columnDefinition="BIGINT UNSIGNED")
    public Long id;
    @Column(nullable=false,length=254) public String email;
    @JsonIgnore @Column(name="password_hash",nullable=false,length=255) public String passwordHash;
    @Column(name="display_name",nullable=false,length=120) public String displayName;
    @Enumerated(EnumType.STRING) @Column(nullable=false,length=16) public Role role=Role.user;
    @Column(nullable=false) public boolean enabled=true;
    @Column(name="created_at",nullable=false,updatable=false) public LocalDateTime createdAt;
    @Column(name="updated_at",nullable=false) public LocalDateTime updatedAt;
    @PrePersist void createTimestamps(){createdAt=LocalDateTime.now(ZoneOffset.UTC);updatedAt=createdAt;}
    @PreUpdate void updateTimestamp(){updatedAt=LocalDateTime.now(ZoneOffset.UTC);}
    public UserDtos.View view(){return new UserDtos.View(id,email,displayName,role.name(),enabled,createdAt,updatedAt);}
}
